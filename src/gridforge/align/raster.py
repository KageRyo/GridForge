"""Raster reprojection and canonical-cell aggregation."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import geopandas as gpd
import numpy as np
import rasterio
from affine import Affine
from pyproj import CRS
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import reproject

from gridforge.errors import DatasetError
from gridforge.grid.build import get_grid_spec
from gridforge.io.datasets import _crs_label, _resolved_crs

RasterAggregation = Literal["mean", "min", "max"]
_AGGREGATION_RESAMPLING = {
    "mean": Resampling.average,
    "min": Resampling.min,
    "max": Resampling.max,
}
_REPROJECTION_RESAMPLING = {
    "nearest": Resampling.nearest,
    "bilinear": Resampling.bilinear,
    "cubic": Resampling.cubic,
}


def align_raster(
    path: str | Path,
    grid: gpd.GeoDataFrame,
    *,
    aggregation: RasterAggregation,
    band: int = 1,
    source_crs: str | CRS | None = None,
    resampling: str | None = None,
    value_name: str | None = None,
) -> gpd.GeoDataFrame:
    """Warp a raster to the grid CRS, then aggregate valid pixels per cell.

    Reprojection uses ``nearest`` by default, or the explicitly selected
    ``nearest``, ``bilinear``, or ``cubic`` method. Cell aggregation is a
    separate, documented mapping: mean→average, min→min, max→max. Nodata and
    cells outside the source footprint remain NaN.
    """
    if aggregation not in _AGGREGATION_RESAMPLING:
        raise DatasetError("aggregation must be mean, min, or max")
    selected_resampling = resampling or "nearest"
    if selected_resampling not in _REPROJECTION_RESAMPLING:
        allowed = ", ".join(_REPROJECTION_RESAMPLING)
        raise DatasetError(f"resampling must be one of: {allowed}")
    if band < 1:
        raise DatasetError("band index must be a positive one-based integer")

    spec = get_grid_spec(grid)
    input_path = Path(path)
    output_name = value_name or input_path.stem
    if not output_name or output_name in grid.columns:
        raise DatasetError("raster value_name must be nonempty and cannot match a grid column")
    output_column = f"{output_name}_{aggregation}"
    if output_column in grid.columns:
        raise DatasetError(f"raster output column conflicts with grid: {output_column}")

    row_start, row_end, col_start, col_end = spec.index_extent
    width = col_end - col_start + 1
    height = row_end - row_start + 1
    left = spec.origin.x + col_start * spec.cell_size
    top = spec.origin.y - row_start * spec.cell_size
    cell_size = float(spec.cell_size)
    target_transform = Affine.translation(float(left), float(top)) @ Affine.scale(
        cell_size, -cell_size
    )
    destination = np.full((height, width), np.nan, dtype="float64")
    source_nodata: float | int | None = None

    try:
        with rasterio.open(input_path) as source:
            resolved_crs = _resolved_crs(source.crs, source_crs)
            source_nodata = source.nodata
            if band > source.count:
                raise DatasetError(f"band index {band} exceeds raster band count {source.count}")
            with WarpedVRT(
                source,
                src_crs=resolved_crs,
                crs=spec.crs,
                resampling=_REPROJECTION_RESAMPLING[selected_resampling],
                nodata=np.nan,
                dtype="float64",
                init_dest_nodata=True,
            ) as warped:
                reproject(
                    source=rasterio.band(warped, band),
                    destination=destination,
                    src_transform=warped.transform,
                    src_crs=warped.crs,
                    src_nodata=warped.nodata,
                    dst_transform=target_transform,
                    dst_crs=spec.crs,
                    dst_nodata=np.nan,
                    resampling=_AGGREGATION_RESAMPLING[aggregation],
                    init_dest_nodata=True,
                )
    except DatasetError:
        raise
    except Exception as exc:
        raise DatasetError(f"cannot align raster {input_path}: {exc}") from exc

    result = grid.copy()
    result[output_column] = destination.reshape(-1)
    result.attrs["gridforge_operation"] = {
        "operation": "raster_alignment",
        "source": str(input_path),
        "source_crs": _crs_label(resolved_crs),
        "target_crs": spec.crs_id,
        "grid_fingerprint": spec.fingerprint,
        "grid_spec": spec.to_dict(),
        "aggregation": aggregation,
        "aggregation_resampling": _AGGREGATION_RESAMPLING[aggregation].name,
        "resampling": selected_resampling,
        "band": band,
        "nodata": None if source_nodata is None else str(source_nodata),
        "output_column": output_column,
    }
    return result
