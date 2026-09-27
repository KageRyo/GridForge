"""Deterministic point-to-grid aggregation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Literal

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
from shapely.geometry import Point

from gridforge.errors import DatasetError
from gridforge.grid.build import get_grid_spec

PointAggregation = Literal["count", "sum", "mean", "min", "max"]


def _point_frame(
    points: gpd.GeoDataFrame | pd.DataFrame,
    *,
    x_column: str,
    y_column: str,
    source_crs: str | CRS | None,
) -> gpd.GeoDataFrame:
    if isinstance(points, gpd.GeoDataFrame):
        result = points.copy()
        parsed_source_crs = None
        if source_crs is not None:
            try:
                parsed_source_crs = CRS.from_user_input(source_crs)
            except Exception as exc:
                raise DatasetError(f"invalid explicit source CRS: {source_crs!r}") from exc
        if result.crs is None:
            if parsed_source_crs is None:
                raise DatasetError("source CRS is unknown; provide --source-crs explicitly")
            result = result.set_crs(parsed_source_crs)
        elif parsed_source_crs is not None and not parsed_source_crs.equals(result.crs):
            raise DatasetError("explicit source CRS conflicts with embedded CRS")
        if result.geometry.isna().any() or result.geometry.is_empty.any():
            raise DatasetError("point dataset contains null or empty geometries")
        if not result.geometry.geom_type.eq("Point").all():
            raise DatasetError("point alignment requires Point geometries")
        coordinates = np.array([(geom.x, geom.y) for geom in result.geometry], dtype=float)
    else:
        missing = [name for name in (x_column, y_column) if name not in points.columns]
        if missing:
            raise DatasetError(f"point table is missing coordinate column(s): {', '.join(missing)}")
        if source_crs is None:
            raise DatasetError("source CRS is unknown; provide --source-crs explicitly")
        try:
            parsed_source_crs = CRS.from_user_input(source_crs)
        except Exception as exc:
            raise DatasetError(f"invalid explicit source CRS: {source_crs!r}") from exc
        try:
            x_values = pd.to_numeric(points[x_column], errors="raise").to_numpy(dtype=float)
            y_values = pd.to_numeric(points[y_column], errors="raise").to_numpy(dtype=float)
        except (TypeError, ValueError) as exc:
            raise DatasetError("point coordinates must be numeric") from exc
        if not np.isfinite(x_values).all() or not np.isfinite(y_values).all():
            raise DatasetError("point coordinates must be finite and non-null")
        result = gpd.GeoDataFrame(
            points.copy(),
            geometry=[Point(x, y) for x, y in zip(x_values, y_values, strict=True)],
            crs=parsed_source_crs,
        )
        coordinates = np.column_stack((x_values, y_values))
    if not np.isfinite(coordinates).all():
        raise DatasetError("point coordinates must be finite and non-null")
    return result


def _aggregation_list(value: str | Sequence[str]) -> tuple[PointAggregation, ...]:
    values = [value] if isinstance(value, str) else list(value)
    allowed = {"count", "sum", "mean", "min", "max"}
    if not values or any(item not in allowed for item in values):
        raise DatasetError("point aggregations must be count, sum, mean, min, or max")
    if len(set(values)) != len(values):
        raise DatasetError("point aggregations cannot contain duplicates")
    return tuple(values)  # type: ignore[return-value]


def _aggregate(values: pd.Series, operation: PointAggregation) -> int | float | None:
    present = values.dropna()
    if operation == "count":
        return int(len(present))
    if present.empty:
        return None
    try:
        numeric = pd.to_numeric(present, errors="raise").to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise DatasetError(f"{operation} aggregation requires numeric values") from exc
    if operation == "sum":
        return math.fsum(sorted(numeric.tolist()))
    if operation == "mean":
        return math.fsum(sorted(numeric.tolist())) / len(numeric)
    if operation == "min":
        return float(numeric.min())
    return float(numeric.max())


def align_points(
    points: gpd.GeoDataFrame | pd.DataFrame,
    grid: gpd.GeoDataFrame,
    *,
    aggregations: Mapping[str, str | Sequence[str]],
    x_column: str = "x",
    y_column: str = "y",
    source_crs: str | CRS | None = None,
) -> gpd.GeoDataFrame:
    """Assign points to canonical cells and aggregate requested attributes.

    The returned frame contains every grid cell. ``point_count`` counts valid
    point records, while empty numeric aggregates and empty-cell values remain
    null; an empty ``count`` result is zero.
    """
    spec = get_grid_spec(grid)
    if not aggregations:
        raise DatasetError("at least one value aggregation is required")
    points_frame = _point_frame(
        points,
        x_column=x_column,
        y_column=y_column,
        source_crs=source_crs,
    )
    for column in aggregations:
        if column not in points_frame.columns:
            raise DatasetError(f"point value column does not exist: {column}")
    try:
        points_in_grid = points_frame.to_crs(spec.crs)
    except Exception as exc:
        raise DatasetError(f"cannot reproject point dataset: {exc}") from exc

    operations = {column: _aggregation_list(value) for column, value in aggregations.items()}
    output_names = [
        f"{column}_{operation}" for column, values in operations.items() for operation in values
    ]
    if len(output_names) != len(set(output_names)):
        raise DatasetError("aggregation output column names are not unique")
    reserved = set(grid.columns) | {"point_count"}
    collisions = sorted(reserved.intersection(output_names))
    if collisions:
        joined = ", ".join(collisions)
        raise DatasetError(f"aggregation output conflicts with grid columns: {joined}")

    rows_by_cell: dict[str, list[int]] = {str(value): [] for value in grid["grid_id"]}
    for index, point in enumerate(points_in_grid.geometry):
        row_column = spec.cell_index(point.x, point.y)
        if row_column is None:
            continue
        row, column = row_column
        key = f"{row}:{column}"
        if key in rows_by_cell:
            rows_by_cell[key].append(index)

    result = grid.copy()
    point_counts: list[int] = []
    aggregate_values: dict[str, list[int | float | None]] = {name: [] for name in output_names}
    for grid_id in result["grid_id"].astype(str):
        point_indexes = rows_by_cell[grid_id]
        point_counts.append(len(point_indexes))
        for value_column, value_operations in operations.items():
            values = points_in_grid.iloc[point_indexes][value_column]
            for operation in value_operations:
                name = f"{value_column}_{operation}"
                aggregate_values[name].append(_aggregate(values, operation))
    result["point_count"] = point_counts
    for name, values in aggregate_values.items():
        result[name] = values
    return result
