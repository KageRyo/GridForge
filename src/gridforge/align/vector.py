"""Polygon-to-grid area coverage and attribute aggregation."""

from __future__ import annotations

import math
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from urllib.parse import quote

import geopandas as gpd
import pandas as pd
from pyproj import CRS
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from gridforge.errors import DatasetError
from gridforge.grid.build import get_grid_spec
from gridforge.io.datasets import _resolved_crs


def _category_name(value: object) -> str:
    return unicodedata.normalize("NFC", str(value)).strip()


def _category_column(category_column: str, category: str) -> str:
    encoded = quote(category, safe="") or "%00"
    return f"{category_column}__{encoded}__coverage_ratio"


def _normalize_polygons(
    polygons: gpd.GeoDataFrame,
    *,
    target_crs: CRS,
    source_crs: str | CRS | None,
) -> gpd.GeoDataFrame:
    if not isinstance(polygons, gpd.GeoDataFrame):
        raise DatasetError("polygon alignment requires a GeoDataFrame")
    crs = _resolved_crs(polygons.crs, source_crs)
    result = polygons.set_crs(crs) if polygons.crs is None else polygons.copy()
    if result.empty:
        try:
            return result.to_crs(target_crs)
        except Exception as exc:
            raise DatasetError(f"cannot reproject polygon dataset: {exc}") from exc
    if result.geometry.isna().any() or result.geometry.is_empty.any():
        raise DatasetError("polygon dataset contains null or empty geometries")
    supported = result.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if not supported.all():
        raise DatasetError("polygon alignment requires Polygon or MultiPolygon geometries")
    valid = result.geometry.is_valid
    if not valid.all():
        invalid_count = int((~valid).sum())
        raise DatasetError(
            f"polygon dataset contains {invalid_count} invalid polygon geometry row(s)"
        )
    try:
        return result.to_crs(target_crs)
    except Exception as exc:
        raise DatasetError(f"cannot reproject polygon dataset: {exc}") from exc


def _numeric_values(polygons: gpd.GeoDataFrame, column: str) -> pd.Series:
    try:
        return pd.to_numeric(polygons[column], errors="raise")
    except (TypeError, ValueError) as exc:
        raise DatasetError(f"polygon numeric column must contain numeric values: {column}") from exc


def align_polygons(
    polygons: gpd.GeoDataFrame,
    grid: gpd.GeoDataFrame,
    *,
    category_column: str | None = None,
    numeric_columns: Sequence[str] = (),
    source_crs: str | CRS | None = None,
) -> gpd.GeoDataFrame:
    """Aggregate polygon intersections to a complete canonical grid.

    Unique coverage is the area of the union of intersections divided by the
    cell area. Category coverage uses a union independently per category;
    overlapping categories may therefore have ratios whose sum exceeds one.
    Numeric weighted means weight each feature value by its intersection area.
    """
    spec = get_grid_spec(grid)
    required = list(numeric_columns)
    if category_column is not None:
        required.append(category_column)
    missing = sorted(set(required) - set(polygons.columns))
    if missing:
        raise DatasetError(f"polygon dataset is missing attribute column(s): {', '.join(missing)}")
    if len(set(numeric_columns)) != len(numeric_columns):
        raise DatasetError("numeric_columns cannot contain duplicates")

    source = _normalize_polygons(
        polygons,
        target_crs=spec.crs,
        source_crs=source_crs,
    )
    numeric = {column: _numeric_values(source, column) for column in numeric_columns}

    categories: list[str] = []
    category_by_row: dict[int, str] = {}
    if category_column is not None:
        for position, value in enumerate(source[category_column].tolist()):
            if pd.isna(value):
                continue
            category = _category_name(value)
            categories.append(category)
            category_by_row[position] = category
    category_values = sorted(set(categories))
    category_outputs = {
        category: _category_column(category_column or "category", category)
        for category in category_values
    }
    if len(set(category_outputs.values())) != len(category_outputs):
        raise DatasetError("normalized category names produce duplicate output columns")

    output_names = ["polygon_count", "polygon_coverage_ratio"]
    if category_column is not None:
        output_names.append(f"dominant_{category_column}")
        output_names.extend(category_outputs.values())
    output_names.extend(f"{column}_weighted_mean" for column in numeric_columns)
    if len(set(output_names)) != len(output_names):
        raise DatasetError("polygon aggregation output column names are not unique")
    collisions = sorted(set(output_names).intersection(grid.columns))
    if collisions:
        raise DatasetError(f"polygon output conflicts with grid columns: {', '.join(collisions)}")

    spatial_index = source.sindex if not source.empty else None
    result = grid.copy()
    polygon_counts: list[int] = []
    coverage_values: list[float] = []
    dominant_values: list[str | None] = []
    category_ratios: dict[str, list[float]] = {category: [] for category in category_values}
    weighted_values: dict[str, list[float | None]] = {column: [] for column in numeric_columns}

    for cell in grid.geometry:
        if spatial_index is None:
            candidate_indexes = []
        else:
            candidate_indexes = sorted(spatial_index.query(cell, predicate="intersects").tolist())
        intersection_geometries = []
        category_geometries: dict[str, list[Polygon | MultiPolygon]] = defaultdict(list)
        weighted_pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
        intersecting_features = 0
        for position in candidate_indexes:
            intersection = source.geometry.iloc[position].intersection(cell)
            area = float(intersection.area)
            if intersection.is_empty or area <= 0.0:
                continue
            intersecting_features += 1
            intersection_geometries.append(intersection)
            category = category_by_row.get(position)
            if category is not None:
                category_geometries[category].append(intersection)
            for column in numeric_columns:
                value = numeric[column].iloc[position]
                if pd.notna(value):
                    weighted_pairs[column].append((float(value), area))

        cell_area = float(cell.area)
        if cell_area <= 0.0:
            raise DatasetError("canonical grid contains a cell with nonpositive area")
        union_area = (
            float(unary_union(intersection_geometries).area) if intersection_geometries else 0.0
        )
        coverage_values.append(min(max(union_area / cell_area, 0.0), 1.0))
        polygon_counts.append(intersecting_features)

        if category_column is not None:
            areas = {
                category: float(unary_union(category_geometries[category]).area)
                if category_geometries[category]
                else 0.0
                for category in category_values
            }
            for category in category_values:
                category_ratios[category].append(min(max(areas[category] / cell_area, 0.0), 1.0))
            present_categories = [category for category in category_values if areas[category] > 0]
            dominant_values.append(
                min(present_categories, key=lambda category: (-areas[category], category))
                if present_categories
                else None
            )

        for column in numeric_columns:
            pairs = sorted(weighted_pairs[column])
            total_area = math.fsum(area for _, area in pairs)
            if total_area == 0:
                weighted_values[column].append(None)
            else:
                numerator = math.fsum(value * area for value, area in pairs)
                weighted_values[column].append(numerator / total_area)

    result["polygon_count"] = polygon_counts
    result["polygon_coverage_ratio"] = coverage_values
    if category_column is not None:
        result[f"dominant_{category_column}"] = dominant_values
        for category, column in category_outputs.items():
            result[column] = category_ratios[category]
    for column, values in weighted_values.items():
        result[f"{column}_weighted_mean"] = values
    return result
