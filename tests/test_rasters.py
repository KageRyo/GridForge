from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from affine import Affine

from gridforge.align.raster import align_raster
from gridforge.errors import DatasetError
from gridforge.grid.build import create_grid
from gridforge.grid.spec import GridSpec


def grid(
    *,
    crs: str = "EPSG:3826",
    cell_size: float = 10,
    bounds: tuple[float, float, float, float] = (0, 0, 20, 20),
    origin: tuple[float, float] = (0, 20),
) -> gpd.GeoDataFrame:
    min_x, min_y, max_x, max_y = bounds
    return create_grid(
        GridSpec.from_mapping(
            {
                "crs": crs,
                "cell_size": cell_size,
                "bounds": {
                    "min_x": min_x,
                    "min_y": min_y,
                    "max_x": max_x,
                    "max_y": max_y,
                },
                "origin": {"x": origin[0], "y": origin[1]},
            }
        )
    )


def write_raster(
    path,
    values: np.ndarray,
    *,
    crs: str | None = "EPSG:3826",
    transform=None,
    nodata: float | None = None,
) -> None:
    height, width = values.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype=values.dtype,
        crs=crs,
        transform=transform or Affine.translation(0, 20) @ Affine.scale(10, -10),
        nodata=nodata,
    ) as dataset:
        dataset.write(values, 1)


def test_exact_same_grid_raster_supports_mean_min_and_max(tmp_path) -> None:
    path = tmp_path / "depth.tif"
    values = np.array([[1, 2], [3, 4]], dtype="float32")
    write_raster(path, values)

    mean = align_raster(path, grid(), aggregation="mean")
    minimum = align_raster(path, grid(), aggregation="min")
    maximum = align_raster(path, grid(), aggregation="max")

    assert mean["depth_mean"].tolist() == [1.0, 2.0, 3.0, 4.0]
    assert minimum["depth_min"].tolist() == [1.0, 2.0, 3.0, 4.0]
    assert maximum["depth_max"].tolist() == [1.0, 2.0, 3.0, 4.0]
    assert mean.attrs["gridforge_operation"]["resampling"] == "nearest"
    assert mean.attrs["gridforge_operation"]["aggregation"] == "mean"


@pytest.mark.parametrize(
    ("aggregation", "expected"),
    [
        ("mean", [3.5, 5.5, 11.5, 13.5]),
        ("min", [1.0, 3.0, 9.0, 11.0]),
        ("max", [6.0, 8.0, 14.0, 16.0]),
    ],
)
def test_different_raster_resolution_uses_declared_cell_aggregation(
    tmp_path, aggregation, expected
) -> None:
    path = tmp_path / "surface.tif"
    values = np.arange(1, 17, dtype="float32").reshape(4, 4)
    write_raster(path, values, transform=Affine.translation(0, 20) @ Affine.scale(5, -5))

    result = align_raster(path, grid(), aggregation=aggregation)

    assert result[f"surface_{aggregation}"].tolist() == expected


def test_nodata_and_uncovered_cells_remain_nan(tmp_path) -> None:
    path = tmp_path / "partial.tif"
    values = np.array([[1, -9999], [3, 4]], dtype="float32")
    write_raster(path, values, nodata=-9999)

    result = align_raster(path, grid(), aggregation="mean")

    assert result["partial_mean"].iloc[0] == 1.0
    assert np.isnan(result["partial_mean"].iloc[1])
    assert result["partial_mean"].iloc[2] == 3.0
    assert result["partial_mean"].iloc[3] == 4.0


def test_raster_reprojection_to_grid_crs_and_extent(tmp_path) -> None:
    from pyproj import Transformer

    x0, y0 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform(120.0, 23.0)
    target = grid(
        crs="EPSG:3857",
        cell_size=1000,
        bounds=(x0, y0, x0 + 2000, y0 + 2000),
        origin=(x0, y0 + 2000),
    )
    path = tmp_path / "geographic.tif"
    values = np.array([[1, 2], [3, 4]], dtype="float32")
    write_raster(
        path,
        values,
        crs="EPSG:4326",
        transform=Affine.translation(120.0, 23.02) @ Affine.scale(0.01, -0.01),
    )

    result = align_raster(path, target, aggregation="mean", resampling="bilinear")

    assert result.crs.to_epsg() == 3857
    assert result["geographic_mean"].notna().any()
    assert result.attrs["gridforge_operation"]["resampling"] == "bilinear"


def test_raster_crs_and_operation_policies_must_be_valid(tmp_path) -> None:
    unknown_path = tmp_path / "unknown.tif"
    write_raster(
        unknown_path,
        np.array([[1, 2], [3, 4]], dtype="float32"),
        crs=None,
    )
    with pytest.raises(DatasetError, match="source CRS is unknown"):
        align_raster(unknown_path, grid(), aggregation="mean")

    overridden = align_raster(
        unknown_path,
        grid(),
        aggregation="mean",
        source_crs="EPSG:3826",
    )
    assert overridden["unknown_mean"].notna().all()

    with pytest.raises(DatasetError, match="aggregation must be mean, min, or max"):
        align_raster(unknown_path, grid(), aggregation="sum", source_crs="EPSG:3826")

    with pytest.raises(DatasetError, match="resampling must be"):
        align_raster(
            unknown_path,
            grid(),
            aggregation="mean",
            source_crs="EPSG:3826",
            resampling="mode",
        )

    with pytest.raises(DatasetError, match="band index"):
        align_raster(
            unknown_path,
            grid(),
            aggregation="mean",
            source_crs="EPSG:3826",
            band=2,
        )
