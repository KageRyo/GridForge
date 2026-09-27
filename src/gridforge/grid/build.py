"""Build canonical cell geometries and stable per-cell identifiers."""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import box

from gridforge.errors import DatasetError
from gridforge.grid.spec import GridSpec


def create_grid(spec: GridSpec) -> gpd.GeoDataFrame:
    """Create every canonical cell intersecting the requested bounds."""
    row_start, row_end, col_start, col_end = spec.index_extent
    rows: list[dict[str, object]] = []
    for row in range(row_start, row_end + 1):
        top_decimal = spec.origin.y - row * spec.cell_size
        bottom_decimal = top_decimal - spec.cell_size
        top = float(top_decimal)
        bottom = float(bottom_decimal)
        for column in range(col_start, col_end + 1):
            left_decimal = spec.origin.x + column * spec.cell_size
            right_decimal = left_decimal + spec.cell_size
            left = float(left_decimal)
            right = float(right_decimal)
            rows.append(
                {
                    "grid_id": f"{row}:{column}",
                    "grid_fingerprint": spec.fingerprint,
                    "row": row,
                    "column": column,
                    "left": left,
                    "bottom": bottom,
                    "right": right,
                    "top": top,
                    "geometry": box(left, bottom, right, top),
                }
            )
    grid = gpd.GeoDataFrame(rows, geometry="geometry", crs=spec.crs)
    grid.attrs["gridforge_spec"] = spec.to_dict()
    return grid


def get_grid_spec(grid: gpd.GeoDataFrame) -> GridSpec:
    """Recover and verify the GridForge spec attached to a canonical grid."""
    value = grid.attrs.get("gridforge_spec")
    if value is None:
        raise DatasetError("grid is missing GridForge specification metadata")
    try:
        spec = GridSpec.from_mapping(value)
    except ValueError as exc:
        raise DatasetError(f"grid specification metadata is invalid: {exc}") from exc
    if grid.crs is None or not spec.crs.equals(grid.crs):
        raise DatasetError("grid CRS does not match GridForge specification")
    if "grid_fingerprint" not in grid or not grid["grid_fingerprint"].eq(spec.fingerprint).all():
        raise DatasetError("grid fingerprint does not match GridForge specification")
    return spec
