"""Explicit-CRS inspection and loading for spatial source datasets."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import rasterio
from pyproj import CRS
from shapely.geometry import Point

from gridforge.errors import DatasetError
from gridforge.grid.spec import GridSpec

_RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".asc", ".bil", ".grd"}
_VECTOR_SUFFIXES = {".geojson", ".json", ".gpkg", ".shp", ".gml", ".fgb"}


@dataclass(frozen=True)
class DatasetInfo:
    """Spatial metadata reported by :func:`inspect_dataset`."""

    path: str
    kind: Literal["vector", "table", "raster"]
    geometry_type: str | None
    crs: str
    feature_count: int | None
    band_count: int | None
    bounds: tuple[float, float, float, float] | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _crs_label(crs: CRS) -> str:
    authority = crs.to_authority()
    return f"{authority[0]}:{authority[1]}" if authority else crs.to_wkt("WKT2_2019", pretty=False)


def _resolved_crs(embedded: object | None, source_crs: str | CRS | None) -> CRS:
    parsed_embedded: CRS | None = None
    if embedded is not None:
        try:
            parsed_embedded = CRS.from_user_input(embedded)
        except Exception as exc:
            raise DatasetError(f"embedded source CRS is invalid: {embedded!r}") from exc
    if parsed_embedded is None:
        if source_crs is None:
            raise DatasetError("source CRS is unknown; provide --source-crs explicitly")
        try:
            return CRS.from_user_input(source_crs)
        except Exception as exc:
            raise DatasetError(f"invalid explicit source CRS: {source_crs!r}") from exc
    if source_crs is not None:
        try:
            requested = CRS.from_user_input(source_crs)
        except Exception as exc:
            raise DatasetError(f"invalid explicit source CRS: {source_crs!r}") from exc
        if not parsed_embedded.equals(requested):
            raise DatasetError("explicit source CRS conflicts with embedded CRS")
    return parsed_embedded


def _read_table(path: Path) -> pd.DataFrame:
    try:
        if path.suffix.lower() == ".csv":
            return pd.read_csv(path)
        if path.suffix.lower() == ".parquet":
            return pd.read_parquet(path)
    except Exception as exc:
        raise DatasetError(f"cannot read tabular dataset {path}: {exc}") from exc
    raise DatasetError(f"unsupported tabular input format: {path.suffix or '<none>'}")


def _table_coordinates(
    table: pd.DataFrame,
    *,
    x_column: str,
    y_column: str,
) -> tuple[np.ndarray, np.ndarray]:
    missing = [name for name in (x_column, y_column) if name not in table.columns]
    if missing:
        raise DatasetError(f"point table is missing coordinate column(s): {', '.join(missing)}")
    try:
        x_values = pd.to_numeric(table[x_column], errors="raise").to_numpy(dtype=float)
        y_values = pd.to_numeric(table[y_column], errors="raise").to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise DatasetError("point coordinates must be numeric") from exc
    if not np.isfinite(x_values).all() or not np.isfinite(y_values).all():
        raise DatasetError("point coordinates must be finite and non-null")
    return x_values, y_values


def _is_geoparquet(path: Path) -> bool:
    if path.suffix.lower() != ".parquet":
        return False
    try:
        metadata = pq.read_schema(path).metadata or {}
    except Exception as exc:
        raise DatasetError(f"cannot inspect Parquet dataset {path}: {exc}") from exc
    return b"geo" in metadata


def _read_geodataframe(path: Path) -> gpd.GeoDataFrame:
    try:
        if path.suffix.lower() == ".parquet" and _is_geoparquet(path):
            return gpd.read_parquet(path)
        if path.suffix.lower() in _VECTOR_SUFFIXES:
            return gpd.read_file(path)
    except Exception as exc:
        raise DatasetError(f"cannot read vector dataset {path}: {exc}") from exc
    raise DatasetError(f"unsupported vector input format: {path.suffix or '<none>'}")


def _bounds_tuple(values: object) -> tuple[float, float, float, float] | None:
    array = np.asarray(values, dtype=float)
    if array.size != 4 or not np.isfinite(array).all():
        return None
    return tuple(float(value) for value in array)  # type: ignore[return-value]


def inspect_dataset(
    path: str | Path,
    *,
    source_crs: str | CRS | None = None,
    x_column: str = "x",
    y_column: str = "y",
) -> DatasetInfo:
    """Inspect vector, coordinate-table, or raster input without guessing CRS."""
    input_path = Path(path)
    suffix = input_path.suffix.lower()
    if suffix in _RASTER_SUFFIXES:
        try:
            with rasterio.open(input_path) as dataset:
                crs = _resolved_crs(dataset.crs, source_crs)
                return DatasetInfo(
                    str(input_path),
                    "raster",
                    "Raster",
                    _crs_label(crs),
                    None,
                    dataset.count,
                    _bounds_tuple(dataset.bounds),
                )
        except DatasetError:
            raise
        except Exception as exc:
            raise DatasetError(f"cannot inspect raster dataset {input_path}: {exc}") from exc

    if suffix == ".csv" or (suffix == ".parquet" and not _is_geoparquet(input_path)):
        table = _read_table(input_path)
        x_values, y_values = _table_coordinates(table, x_column=x_column, y_column=y_column)
        crs = _resolved_crs(None, source_crs)
        if not len(table):
            bounds = None
        else:
            bounds = (
                float(x_values.min()),
                float(y_values.min()),
                float(x_values.max()),
                float(y_values.max()),
            )
        return DatasetInfo(
            str(input_path), "table", "Point", _crs_label(crs), len(table), None, bounds
        )

    vector = _read_geodataframe(input_path)
    crs = _resolved_crs(vector.crs, source_crs)
    geometry_types = sorted({str(value) for value in vector.geometry.geom_type.dropna().unique()})
    geometry_type = ", ".join(geometry_types) if geometry_types else None
    bounds = _bounds_tuple(vector.total_bounds) if not vector.empty else None
    return DatasetInfo(
        str(input_path),
        "vector",
        geometry_type,
        _crs_label(crs),
        len(vector),
        None,
        bounds,
    )


def load_vector(
    path: str | Path,
    *,
    source_crs: str | CRS | None = None,
) -> gpd.GeoDataFrame:
    """Load a supported vector file and require an explicit, consistent CRS."""
    input_path = Path(path)
    vector = _read_geodataframe(input_path)
    crs = _resolved_crs(vector.crs, source_crs)
    if vector.crs is None:
        vector = vector.set_crs(crs)
    return vector


def load_points(
    path: str | Path,
    *,
    x_column: str = "x",
    y_column: str = "y",
    source_crs: str | CRS | None = None,
) -> gpd.GeoDataFrame:
    """Load point geometry or an x/y table with an explicit source CRS."""
    input_path = Path(path)
    if input_path.suffix.lower() in {".csv", ".parquet"} and not _is_geoparquet(input_path):
        table = _read_table(input_path)
        crs = _resolved_crs(None, source_crs)
        x_values, y_values = _table_coordinates(table, x_column=x_column, y_column=y_column)
        result = gpd.GeoDataFrame(
            table.copy(),
            geometry=[Point(x, y) for x, y in zip(x_values, y_values, strict=True)],
            crs=crs,
        )
    else:
        result = load_vector(input_path, source_crs=source_crs)
        if result.geometry.isna().any() or result.geometry.is_empty.any():
            raise DatasetError("point dataset contains null or empty geometries")
        if not result.geometry.geom_type.eq("Point").all():
            raise DatasetError("point alignment requires Point geometries")
    if result.geometry.isna().any() or result.geometry.is_empty.any():
        raise DatasetError("point dataset contains null or empty geometries")
    if not result.geometry.geom_type.eq("Point").all():
        raise DatasetError("point alignment requires Point geometries")
    return result


def write_dataset(dataset: gpd.GeoDataFrame, path: str | Path) -> Path:
    """Write one validated aligned dataset as GridForge GeoParquet.

    Null feature values are retained as nodata and reported as warnings. A
    dataset with structural, identity, geometry, or coverage errors is refused.
    """
    from gridforge.validation import validate_dataset

    report = validate_dataset(dataset)
    errors = [finding.message for finding in report.findings if finding.severity == "ERROR"]
    if errors:
        raise DatasetError("aligned dataset is invalid: " + "; ".join(errors[:3]))
    spec_value = dataset.attrs.get("gridforge_spec")
    if not isinstance(spec_value, dict):
        raise DatasetError("aligned dataset is missing GridForge grid metadata")
    try:
        spec = GridSpec.from_mapping(spec_value)
    except ValueError as exc:
        raise DatasetError(f"aligned dataset grid metadata is invalid: {exc}") from exc
    fingerprint = str(dataset["grid_fingerprint"].iloc[0])
    if fingerprint != spec.fingerprint:
        raise DatasetError("aligned dataset grid fingerprint does not match its specification")

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        dataset.to_parquet(output, index=False)
        table = pq.read_table(output)
        metadata = dict(table.schema.metadata or {})
        metadata[b"gridforge:grid_fingerprint"] = fingerprint.encode("utf-8")
        metadata[b"gridforge:grid_spec"] = json.dumps(
            spec.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        operation = dataset.attrs.get("gridforge_operation")
        if operation is not None:
            metadata[b"gridforge:operation"] = json.dumps(
                operation, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        pq.write_table(table.replace_schema_metadata(metadata), output, compression="zstd")
    except Exception as exc:
        raise DatasetError(f"cannot write aligned GeoParquet {output}: {exc}") from exc
    return output


def read_dataset(path: str | Path) -> gpd.GeoDataFrame:
    """Read GridForge GeoParquet and restore its canonical grid identity."""
    from gridforge.validation import validate_dataset

    input_path = Path(path)
    try:
        dataset = gpd.read_parquet(input_path)
        schema_metadata = pq.read_schema(input_path).metadata or {}
    except Exception as exc:
        raise DatasetError(f"cannot read aligned GeoParquet {input_path}: {exc}") from exc
    metadata_fingerprint = schema_metadata.get(b"gridforge:grid_fingerprint")
    metadata_spec = schema_metadata.get(b"gridforge:grid_spec")
    if metadata_fingerprint is None or metadata_spec is None:
        raise DatasetError("GeoParquet is missing GridForge grid metadata")
    try:
        spec_value = json.loads(metadata_spec.decode("utf-8"))
        spec = GridSpec.from_mapping(spec_value)
        fingerprint = metadata_fingerprint.decode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise DatasetError("GridForge grid metadata is invalid") from exc
    if spec.fingerprint != fingerprint:
        raise DatasetError("GridForge grid metadata fingerprint does not match grid specification")
    dataset.attrs["gridforge_spec"] = spec.to_dict()
    operation = schema_metadata.get(b"gridforge:operation")
    if operation is not None:
        try:
            dataset.attrs["gridforge_operation"] = json.loads(operation.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DatasetError("GridForge operation metadata is invalid") from exc
    if dataset.empty or "grid_fingerprint" not in dataset:
        raise DatasetError("aligned dataset has no grid rows")
    if not dataset["grid_fingerprint"].astype(str).eq(fingerprint).all():
        raise DatasetError("aligned dataset grid fingerprint does not match metadata")
    if dataset.crs is None or not spec.crs.equals(dataset.crs):
        raise DatasetError("aligned dataset CRS does not match GridForge grid metadata")
    report = validate_dataset(dataset)
    errors = [finding.message for finding in report.findings if finding.severity == "ERROR"]
    if errors:
        raise DatasetError("aligned dataset is invalid: " + "; ".join(errors[:3]))
    return dataset
