"""Synthetic end-to-end workflow for the GridForge command-line demo."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from shapely.geometry import box

from gridforge.align.points import align_points
from gridforge.align.raster import align_raster
from gridforge.align.vector import align_polygons
from gridforge.errors import DatasetError
from gridforge.grid.build import create_grid
from gridforge.grid.spec import GridSpec
from gridforge.io.datasets import load_points, write_dataset
from gridforge.io.grid import write_grid
from gridforge.join import join_features
from gridforge.provenance import write_provenance
from gridforge.validation import ValidationReport, validate_dataset


def _write_aligned(
    dataset: gpd.GeoDataFrame,
    path: Path,
    *,
    operation: str,
    source: str | list[str],
    grid: gpd.GeoDataFrame,
    parameters: dict[str, object],
) -> None:
    write_dataset(dataset, path)
    write_provenance(
        path,
        operation=operation,
        source=source,
        grid=grid,
        parameters=parameters,
    )


def run_demo(output_dir: str | Path) -> ValidationReport:
    """Create synthetic spatial inputs and run the complete v0.1 workflow."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    specification_path = directory / "grid.yaml"
    specification_path.write_text(
        """crs: EPSG:3857
cell_size: 20
bounds:
  min_x: 0
  min_y: 0
  max_x: 80
  max_y: 80
origin:
  x: 0
  y: 80
""",
        encoding="utf-8",
    )
    spec = GridSpec.from_yaml(specification_path)
    grid = create_grid(spec)
    grid_path = directory / "grid.parquet"
    write_grid(grid, grid_path)
    write_provenance(
        grid_path,
        operation="grid_build",
        source=str(specification_path),
        grid=grid,
        parameters={"grid_spec": spec.to_dict()},
    )

    points_path = directory / "points.csv"
    pd.DataFrame(
        {
            "station": ["P-01", "P-02", "P-03"],
            "x": [10.0, 30.0, 70.0],
            "y": [70.0, 50.0, 10.0],
            "rainfall_mm": [12.0, 18.0, 9.0],
        }
    ).to_csv(points_path, index=False)
    point_frame = load_points(points_path, source_crs="EPSG:3857")
    point_output = directory / "rainfall.parquet"
    point_result = align_points(
        point_frame,
        grid,
        aggregations={"rainfall_mm": "mean"},
    )
    _write_aligned(
        point_result,
        point_output,
        operation="point_alignment",
        source=str(points_path),
        grid=grid,
        parameters={"source_crs": "EPSG:3857", "aggregation": {"rainfall_mm": "mean"}},
    )

    polygon_path = directory / "landuse.geojson"
    polygons = gpd.GeoDataFrame(
        {"landuse": ["park", "built"], "impervious": [0.1, 0.9]},
        geometry=[box(0, 40, 40, 80), box(40, 0, 80, 40)],
        crs="EPSG:3857",
    )
    polygons.to_file(polygon_path, driver="GeoJSON")
    polygon_output = directory / "landuse.parquet"
    polygon_result = align_polygons(
        polygons,
        grid,
        category_column="landuse",
        numeric_columns=("impervious",),
    )
    _write_aligned(
        polygon_result,
        polygon_output,
        operation="vector_alignment",
        source=str(polygon_path),
        grid=grid,
        parameters={
            "source_crs": "EPSG:3857",
            "category_column": "landuse",
            "numeric_columns": ["impervious"],
        },
    )

    raster_path = directory / "elevation.tif"
    transform = Affine.translation(0, 80) @ Affine.scale(20, -20)
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=transform,
        nodata=-9999.0,
    ) as raster:
        raster.write(np.arange(16, dtype="float32").reshape(4, 4), 1)
    raster_output = directory / "elevation.parquet"
    raster_result = align_raster(raster_path, grid, aggregation="mean")
    _write_aligned(
        raster_result,
        raster_output,
        operation="raster_alignment",
        source=str(raster_path),
        grid=grid,
        parameters={
            "source_crs": "EPSG:3857",
            "aggregation": "mean",
            "resampling": "nearest",
            "band": 1,
        },
    )

    joined = join_features(grid, point_result, polygon_result, raster_result)
    joined_path = directory / "features.parquet"
    _write_aligned(
        joined,
        joined_path,
        operation="feature_join",
        source=[str(point_output), str(polygon_output), str(raster_output)],
        grid=grid,
        parameters={"feature_datasets": 3},
    )
    report = validate_dataset(joined, grid=grid)
    if report.exit_code:
        raise DatasetError("synthetic demo output did not pass validation")
    return report
