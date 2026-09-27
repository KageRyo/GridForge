from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon, box

from gridforge.align.vector import align_polygons
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


def test_polygon_partial_overlap_uses_intersection_area_and_weighted_mean() -> None:
    polygons = gpd.GeoDataFrame(
        {
            "landuse": ["road", "road"],
            "elevation": [10.0, 20.0],
        },
        geometry=[box(0, 15, 5, 20), box(5, 10, 10, 20)],
        crs="EPSG:3826",
    )

    result = align_polygons(
        polygons,
        grid(),
        category_column="landuse",
        numeric_columns=["elevation"],
    ).set_index("grid_id")

    assert result.loc["0:0", "polygon_coverage_ratio"] == 0.75
    assert result.loc["0:0", "landuse__road__coverage_ratio"] == 0.75
    assert result.loc["0:0", "dominant_landuse"] == "road"
    assert result.loc["0:0", "elevation_weighted_mean"] == pytest.approx(50 / 3)
    assert result.loc["0:1", "polygon_coverage_ratio"] == 0.0


def test_boundary_touch_has_zero_coverage_and_does_not_fill_cell() -> None:
    polygons = gpd.GeoDataFrame(
        {"landuse": ["outside"]},
        geometry=[box(20, 18, 22, 19)],
        crs="EPSG:3826",
    )

    result = align_polygons(polygons, grid(), category_column="landuse")

    assert result["polygon_coverage_ratio"].eq(0.0).all()
    assert result["dominant_landuse"].isna().all()


def test_coverage_only_mode_needs_no_source_attributes() -> None:
    polygons = gpd.GeoDataFrame(
        geometry=[box(0, 10, 5, 20)],
        crs="EPSG:3826",
    )

    result = align_polygons(polygons, grid())

    assert result.loc[0, "polygon_count"] == 1
    assert result.loc[0, "polygon_coverage_ratio"] == 0.5


def test_overlapping_polygons_use_union_for_unique_coverage() -> None:
    polygons = gpd.GeoDataFrame(
        {"landuse": ["wood", "wood"]},
        geometry=[box(0, 10, 7, 20), box(3, 10, 10, 20)],
        crs="EPSG:3826",
    )

    result = align_polygons(polygons, grid(), category_column="landuse").set_index("grid_id")

    assert result.loc["0:0", "polygon_coverage_ratio"] == 1.0
    assert result.loc["0:0", "landuse__wood__coverage_ratio"] == 1.0
    assert result["polygon_coverage_ratio"].between(0.0, 1.0).all()


def test_dominant_category_ties_break_by_normalized_category_name() -> None:
    polygons = gpd.GeoDataFrame(
        {"landuse": ["road", "forest"]},
        geometry=[box(0, 15, 5, 20), box(5, 15, 10, 20)],
        crs="EPSG:3826",
    )

    result = align_polygons(polygons, grid(), category_column="landuse").set_index("grid_id")

    assert result.loc["0:0", "dominant_landuse"] == "forest"
    assert result.loc["0:0", "landuse__forest__coverage_ratio"] == 0.25
    assert result.loc["0:0", "landuse__road__coverage_ratio"] == 0.25


def test_multipolygon_is_supported() -> None:
    polygons = gpd.GeoDataFrame(
        {"landuse": ["park"]},
        geometry=[MultiPolygon([box(0, 18, 2, 20), box(8, 18, 10, 20)])],
        crs="EPSG:3826",
    )

    result = align_polygons(polygons, grid(), category_column="landuse")

    assert result.iloc[0]["polygon_coverage_ratio"] == 0.08


def test_invalid_geometries_and_non_polygon_inputs_are_rejected() -> None:
    invalid = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])
    bad_geometry = gpd.GeoDataFrame({"landuse": ["x"]}, geometry=[invalid], crs="EPSG:3826")
    with pytest.raises(DatasetError, match="invalid polygon geometry"):
        align_polygons(bad_geometry, grid(), category_column="landuse")

    line = gpd.GeoDataFrame({"landuse": ["x"]}, geometry=[Point(1, 2)], crs="EPSG:3826")
    with pytest.raises(DatasetError, match="Polygon or MultiPolygon"):
        align_polygons(line, grid(), category_column="landuse")


def test_polygon_alignment_requires_explicit_and_consistent_crs() -> None:
    unknown = gpd.GeoDataFrame({"landuse": ["x"]}, geometry=[box(0, 0, 1, 1)])
    with pytest.raises(DatasetError, match="source CRS is unknown"):
        align_polygons(unknown, grid(), category_column="landuse")

    known = unknown.set_crs("EPSG:3826")
    with pytest.raises(DatasetError, match="conflicts with embedded CRS"):
        align_polygons(
            known,
            grid(),
            category_column="landuse",
            source_crs="EPSG:4326",
        )
