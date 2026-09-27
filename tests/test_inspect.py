from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from gridforge.errors import DatasetError
from gridforge.io.datasets import inspect_dataset, load_points


def test_inspect_reports_geoparquet_geometry_crs_count_and_bounds(tmp_path) -> None:
    source = gpd.GeoDataFrame(
        {"site": ["A", "B"]},
        geometry=[Point(1, 2), Point(3, 4)],
        crs="EPSG:3826",
    )
    path = tmp_path / "sites.parquet"
    source.to_parquet(path, index=False)

    info = inspect_dataset(path)

    assert info.kind == "vector"
    assert info.geometry_type == "Point"
    assert info.crs == "EPSG:3826"
    assert info.feature_count == 2
    assert info.bounds == (1.0, 2.0, 3.0, 4.0)


def test_inspect_requires_explicit_crs_for_csv_coordinates(tmp_path) -> None:
    path = tmp_path / "stations.csv"
    pd.DataFrame({"x": [100.0], "y": [200.0], "rainfall": [4.2]}).to_csv(path, index=False)

    with pytest.raises(DatasetError, match="source CRS is unknown"):
        inspect_dataset(path)

    info = inspect_dataset(path, source_crs="EPSG:3826")

    assert info.kind == "table"
    assert info.geometry_type == "Point"
    assert info.crs == "EPSG:3826"
    assert info.feature_count == 1
    assert info.bounds == (100.0, 200.0, 100.0, 200.0)


def test_inspect_does_not_relabel_an_embedded_crs(tmp_path) -> None:
    source = gpd.GeoDataFrame(geometry=[Point(1, 2)], crs="EPSG:3826")
    path = tmp_path / "sites.parquet"
    source.to_parquet(path, index=False)

    with pytest.raises(DatasetError, match="conflicts with embedded CRS"):
        inspect_dataset(path, source_crs="EPSG:4326")


def test_load_points_requires_crs_for_table_and_builds_point_geometry(tmp_path) -> None:
    path = tmp_path / "stations.csv"
    pd.DataFrame({"easting": [10.0], "northing": [20.0], "rainfall": [5]}).to_csv(path, index=False)

    with pytest.raises(DatasetError, match="source CRS is unknown"):
        load_points(path, x_column="easting", y_column="northing")

    points = load_points(
        path,
        x_column="easting",
        y_column="northing",
        source_crs="EPSG:3826",
    )

    assert points.crs.to_epsg() == 3826
    assert points.geometry.iloc[0].equals(Point(10.0, 20.0))
    assert points["rainfall"].iloc[0] == 5
