"""GeoParquet persistence for canonical grids."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pyarrow.parquet as pq

from gridforge.errors import DatasetError
from gridforge.grid.spec import GridSpec

_GRID_COLUMNS = {
    "grid_id",
    "grid_fingerprint",
    "row",
    "column",
    "left",
    "bottom",
    "right",
    "top",
    "geometry",
}


def write_grid(grid: gpd.GeoDataFrame, path: str | Path) -> Path:
    """Write a canonical grid as GeoParquet with GridForge metadata."""
    _validate_grid_schema(grid)
    spec_value = grid.attrs.get("gridforge_spec")
    if not isinstance(spec_value, dict):
        raise DatasetError("grid is missing GridForge specification metadata")
    try:
        spec = GridSpec.from_mapping(spec_value)
    except ValueError as exc:
        raise DatasetError(f"grid specification metadata is invalid: {exc}") from exc
    if grid.crs is None or not spec.crs.equals(grid.crs):
        raise DatasetError("grid CRS does not match GridForge specification")
    if not grid["grid_fingerprint"].astype(str).eq(spec.fingerprint).all():
        raise DatasetError("grid fingerprint does not match GridForge specification")
    from gridforge.validation import validate_grid

    report = validate_grid(grid)
    errors = [finding.message for finding in report.findings if finding.severity == "ERROR"]
    if errors:
        raise DatasetError("grid is invalid: " + "; ".join(errors[:3]))
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    grid.to_parquet(output, index=False)
    table = pq.read_table(output)
    metadata = dict(table.schema.metadata or {})
    metadata[b"gridforge:grid_fingerprint"] = str(grid["grid_fingerprint"].iloc[0]).encode()
    metadata[b"gridforge:grid_spec"] = json.dumps(
        spec.to_dict(), sort_keys=True, separators=(",", ":")
    ).encode()
    pq.write_table(table.replace_schema_metadata(metadata), output, compression="zstd")
    return output


def read_grid(path: str | Path) -> gpd.GeoDataFrame:
    """Read a GeoParquet grid and reject incomplete or ambiguous identity."""
    input_path = Path(path)
    try:
        grid = gpd.read_parquet(input_path)
        table = pq.read_table(input_path)
    except Exception as exc:
        raise DatasetError(f"cannot read grid GeoParquet {input_path}: {exc}") from exc
    _validate_grid_schema(grid)
    metadata_fingerprint = (table.schema.metadata or {}).get(b"gridforge:grid_fingerprint")
    metadata_spec = (table.schema.metadata or {}).get(b"gridforge:grid_spec")
    if metadata_fingerprint is None or metadata_spec is None:
        raise DatasetError("GeoParquet is missing GridForge grid metadata")
    try:
        decoded_fingerprint = metadata_fingerprint.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DatasetError("grid fingerprint metadata is invalid") from exc
    if decoded_fingerprint != str(grid["grid_fingerprint"].iloc[0]):
        raise DatasetError("grid fingerprint metadata does not match grid rows")
    try:
        grid.attrs["gridforge_spec"] = json.loads(metadata_spec.decode())
        spec = GridSpec.from_mapping(grid.attrs["gridforge_spec"])
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise DatasetError("grid specification metadata is invalid") from exc
    if spec.fingerprint != str(grid["grid_fingerprint"].iloc[0]):
        raise DatasetError("grid specification does not match grid fingerprint")
    from gridforge.validation import validate_grid

    report = validate_grid(grid)
    errors = [finding.message for finding in report.findings if finding.severity == "ERROR"]
    if errors:
        raise DatasetError("grid is invalid: " + "; ".join(errors[:3]))
    return grid


def _validate_grid_schema(grid: gpd.GeoDataFrame) -> None:
    missing = sorted(_GRID_COLUMNS - set(grid.columns))
    if missing:
        raise DatasetError(f"grid is missing required columns: {', '.join(missing)}")
    if grid.empty:
        raise DatasetError("grid must contain at least one cell")
    if grid.crs is None:
        raise DatasetError("grid CRS is unknown")
    if grid["grid_id"].isna().any() or grid["grid_id"].duplicated().any():
        raise DatasetError("grid IDs must be non-null and unique")
    fingerprints = grid["grid_fingerprint"].dropna().astype(str).unique()
    if len(fingerprints) != 1 or grid["grid_fingerprint"].isna().any():
        raise DatasetError("grid rows must have one non-null grid fingerprint")
    expected = grid.sort_values(["row", "column"], kind="stable").index
    if not grid.index.equals(expected):
        raise DatasetError("grid rows must be sorted by row and column")
