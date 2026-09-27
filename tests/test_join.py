from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import box

from gridforge.errors import DatasetError
from gridforge.grid.build import create_grid
from gridforge.grid.spec import GridSpec
from gridforge.join import join_features


def grid(origin_x: float = 0) -> gpd.GeoDataFrame:
    return create_grid(
        GridSpec.from_mapping(
            {
                "crs": "EPSG:3826",
                "cell_size": 10,
                "bounds": {"min_x": origin_x, "min_y": 0, "max_x": origin_x + 20, "max_y": 20},
                "origin": {"x": origin_x, "y": 20},
            }
        )
    )


def test_join_combines_aligned_features_in_canonical_grid_order() -> None:
    canonical = grid()
    points = canonical.iloc[[3, 2, 1, 0]].copy()
    points["rainfall_mean"] = [4.0, 3.0, 2.0, 1.0]
    polygons = canonical.copy()
    polygons["landuse_coverage_ratio"] = [0.1, 0.2, 0.3, 0.4]

    joined = join_features(canonical, points, polygons)

    assert joined["grid_id"].tolist() == canonical["grid_id"].tolist()
    assert joined["rainfall_mean"].tolist() == [1.0, 2.0, 3.0, 4.0]
    assert joined["landuse_coverage_ratio"].tolist() == [0.1, 0.2, 0.3, 0.4]
    assert joined.geometry.equals(canonical.geometry)
    assert joined.crs.to_epsg() == 3826


def test_join_rejects_same_shape_grid_with_different_identity() -> None:
    with pytest.raises(DatasetError, match="grid fingerprint mismatch"):
        join_features(grid(), grid(100))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "missing grid IDs"),
        ("extra", "unexpected grid IDs"),
        ("duplicate", "duplicate grid IDs"),
    ],
)
def test_join_rejects_missing_extra_or_duplicate_feature_cells(mutation, message) -> None:
    canonical = grid()
    feature = canonical.copy()
    if mutation == "missing":
        feature = feature.iloc[1:].copy()
    elif mutation == "extra":
        feature.loc[feature.index[0], "grid_id"] = "99:99"
    else:
        feature.loc[feature.index[0], "grid_id"] = feature.iloc[1]["grid_id"]

    with pytest.raises(DatasetError, match=message):
        join_features(canonical, feature)


def test_join_rejects_crs_mismatch_and_changed_cell_geometry() -> None:
    canonical = grid()
    wrong_crs = canonical.copy().set_crs("EPSG:4326", allow_override=True)
    with pytest.raises(DatasetError, match="CRS mismatch"):
        join_features(canonical, wrong_crs)

    wrong_geometry = canonical.copy()
    wrong_geometry.loc[wrong_geometry.index[0], "geometry"] = box(100, 100, 110, 110)
    with pytest.raises(DatasetError, match="geometry mismatch"):
        join_features(canonical, wrong_geometry)


def test_join_rejects_duplicate_feature_names() -> None:
    canonical = grid()
    left = canonical.copy()
    right = canonical.copy()
    left["temperature"] = 1.0
    right["temperature"] = 2.0

    with pytest.raises(DatasetError, match="duplicate feature columns"):
        join_features(canonical, left, right)
