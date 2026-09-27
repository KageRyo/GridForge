from __future__ import annotations

import geopandas as gpd
import pytest

from gridforge.errors import DatasetError
from gridforge.grid.build import create_grid
from gridforge.grid.spec import GridSpec
from gridforge.io.grid import read_grid, write_grid


def test_grid_geoparquet_round_trip_preserves_identity_and_crs(tmp_path) -> None:
    spec = GridSpec.from_mapping(
        {
            "crs": "EPSG:3826",
            "cell_size": 20,
            "bounds": {"min_x": 0, "min_y": 0, "max_x": 40, "max_y": 40},
            "origin": {"x": 0, "y": 40},
        }
    )
    expected = create_grid(spec)
    output = tmp_path / "grid.parquet"

    write_grid(expected, output)
    actual = read_grid(output)

    assert actual["grid_id"].tolist() == expected["grid_id"].tolist()
    assert actual["grid_fingerprint"].tolist() == expected["grid_fingerprint"].tolist()
    assert actual.crs.to_epsg() == 3826
    assert actual.geometry.equals(expected.geometry)


def test_grid_reader_requires_gridforge_identity_metadata(tmp_path) -> None:
    grid = create_grid(
        GridSpec.from_mapping(
            {
                "crs": "EPSG:3826",
                "cell_size": 20,
                "bounds": {"min_x": 0, "min_y": 0, "max_x": 20, "max_y": 20},
                "origin": {"x": 0, "y": 20},
            }
        )
    )
    path = tmp_path / "ordinary.parquet"
    gpd.GeoDataFrame(grid, geometry="geometry", crs=grid.crs).to_parquet(path, index=False)

    with pytest.raises(DatasetError, match="GridForge grid metadata"):
        read_grid(path)
