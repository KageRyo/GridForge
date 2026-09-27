from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from gridforge.align.points import align_points
from gridforge.errors import DatasetError
from gridforge.grid.build import create_grid
from gridforge.grid.spec import GridSpec


def grid() -> gpd.GeoDataFrame:
    return create_grid(
        GridSpec.from_mapping(
            {
                "crs": "EPSG:3826",
                "cell_size": 10,
                "bounds": {"min_x": 0, "min_y": 0, "max_x": 20, "max_y": 20},
                "origin": {"x": 0, "y": 20},
            }
        )
    )


def test_point_alignment_aggregates_all_cells_and_keeps_empty_values_null() -> None:
    points = gpd.GeoDataFrame(
        {"rainfall": [2.0, 4.0, 6.0, 99.0]},
        geometry=[Point(2, 18), Point(8, 12), Point(10, 10), Point(40, 40)],
        crs="EPSG:3826",
    )

    result = align_points(
        points,
        grid(),
        aggregations={"rainfall": ["mean", "sum", "min", "max", "count"]},
    )

    first = result.set_index("grid_id").loc["0:0"]
    second = result.set_index("grid_id").loc["1:1"]
    empty = result.set_index("grid_id").loc["0:1"]
    assert result["grid_id"].tolist() == ["0:0", "0:1", "1:0", "1:1"]
    assert result["point_count"].tolist() == [2, 0, 0, 1]
    assert first["rainfall_mean"] == 3.0
    assert first["rainfall_sum"] == 6.0
    assert first["rainfall_min"] == 2.0
    assert first["rainfall_max"] == 4.0
    assert first["rainfall_count"] == 2
    assert second["rainfall_mean"] == 6.0
    assert pd.isna(empty["rainfall_mean"])
    assert empty["rainfall_count"] == 0


def test_point_boundary_uses_east_and_south_cell_and_extent_is_half_open() -> None:
    points = gpd.GeoDataFrame(
        {"value": [1, 2, 3]},
        geometry=[Point(10, 10), Point(20, 10), Point(10, 0)],
        crs="EPSG:3826",
    )

    result = align_points(points, grid(), aggregations={"value": "count"})

    assert result["point_count"].tolist() == [0, 0, 0, 1]
    assert result["value_count"].tolist() == [0, 0, 0, 1]


def test_point_alignment_transforms_crs_before_cell_lookup() -> None:
    points = gpd.GeoDataFrame(geometry=[Point(120.0, 23.0)], crs="EPSG:4326")
    target = create_grid(
        GridSpec.from_mapping(
            {
                "crs": "EPSG:3857",
                "cell_size": 1000,
                "bounds": {
                    "min_x": 13_350_000,
                    "min_y": 2_620_000,
                    "max_x": 13_360_000,
                    "max_y": 2_640_000,
                },
                "origin": {"x": 13_350_000, "y": 2_640_000},
            }
        )
    )

    points["station_id"] = ["A"]
    result = align_points(points, target, aggregations={"station_id": "count"})

    assert result["point_count"].sum() == 1


def test_point_alignment_rejects_unknown_or_conflicting_crs() -> None:
    unknown = gpd.GeoDataFrame({"value": [3]}, geometry=[Point(1, 2)])
    with pytest.raises(DatasetError, match="source CRS is unknown"):
        align_points(unknown, grid(), aggregations={"value": "mean"})

    known = unknown.set_crs("EPSG:3826")
    with pytest.raises(DatasetError, match="conflicts with embedded CRS"):
        align_points(known, grid(), aggregations={"value": "mean"}, source_crs="EPSG:4326")


def test_point_table_requires_explicit_source_crs() -> None:
    table = pd.DataFrame({"x": [1.0], "y": [2.0], "value": [3.0]})
    with pytest.raises(DatasetError, match="source CRS is unknown"):
        align_points(table, grid(), aggregations={"value": "mean"})


def test_point_alignment_wraps_invalid_explicit_crs() -> None:
    points = gpd.GeoDataFrame({"value": [3.0]}, geometry=[Point(1, 2)])

    with pytest.raises(DatasetError, match="invalid explicit source CRS"):
        align_points(
            points,
            grid(),
            aggregations={"value": "mean"},
            source_crs="not-a-crs",
        )
