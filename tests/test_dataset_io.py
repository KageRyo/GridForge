from __future__ import annotations

import geopandas as gpd
import pytest

from gridforge.errors import DatasetError
from gridforge.grid.build import create_grid
from gridforge.grid.spec import GridSpec
from gridforge.io.datasets import read_dataset, write_dataset


def feature_dataset() -> gpd.GeoDataFrame:
    grid = create_grid(
        GridSpec.from_mapping(
            {
                "crs": "EPSG:3826",
                "cell_size": 10,
                "bounds": {"min_x": 0, "min_y": 0, "max_x": 20, "max_y": 20},
                "origin": {"x": 0, "y": 20},
            }
        )
    )
    grid["value"] = [1.0, None, 3.0, 4.0]
    return grid


def test_aligned_geoparquet_round_trip_preserves_spec_and_identity(tmp_path) -> None:
    source = feature_dataset()
    path = tmp_path / "features.parquet"

    write_dataset(source, path)
    result = read_dataset(path)

    assert result["grid_id"].tolist() == source["grid_id"].tolist()
    assert result["grid_fingerprint"].tolist() == source["grid_fingerprint"].tolist()
    assert result.crs.to_epsg() == 3826
    assert result.attrs["gridforge_spec"] == source.attrs["gridforge_spec"]
    assert result["value"].tolist()[0] == 1.0


def test_aligned_writer_rejects_inconsistent_identity(tmp_path) -> None:
    source = feature_dataset()
    source.loc[source.index[0], "grid_fingerprint"] = "wrong"

    with pytest.raises(DatasetError, match="grid fingerprint"):
        write_dataset(source, tmp_path / "bad.parquet")


def test_aligned_reader_rejects_missing_gridforge_metadata(tmp_path) -> None:
    source = feature_dataset()
    path = tmp_path / "source.parquet"
    source.to_parquet(path, index=False)

    with pytest.raises(DatasetError, match="GridForge grid metadata"):
        read_dataset(path)
