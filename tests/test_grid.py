from __future__ import annotations

import pytest

from gridforge.errors import GridSpecError
from gridforge.grid.build import create_grid
from gridforge.grid.spec import GridSpec


def example_spec() -> GridSpec:
    return GridSpec.from_mapping(
        {
            "crs": "EPSG:3826",
            "cell_size": 10,
            "bounds": {"min_x": 3, "min_y": 7, "max_x": 23, "max_y": 27},
            "origin": {"x": 0, "y": 30},
        }
    )


def test_grid_ids_bounds_and_order_are_deterministic() -> None:
    first = create_grid(example_spec())
    second = create_grid(example_spec())

    assert first["grid_id"].tolist() == [
        "0:0",
        "0:1",
        "0:2",
        "1:0",
        "1:1",
        "1:2",
        "2:0",
        "2:1",
        "2:2",
    ]
    assert first["grid_id"].tolist() == second["grid_id"].tolist()
    assert first["grid_fingerprint"].nunique() == 1
    assert first["grid_fingerprint"].iloc[0] == second["grid_fingerprint"].iloc[0]
    assert first[["row", "column"]].values.tolist() == second[["row", "column"]].values.tolist()
    assert first.iloc[0][["left", "bottom", "right", "top"]].tolist() == [0.0, 20.0, 10.0, 30.0]


def test_grid_indices_are_anchored_to_origin_and_support_negative_values() -> None:
    spec = GridSpec.from_mapping(
        {
            "crs": "EPSG:3826",
            "cell_size": 10,
            "bounds": {"min_x": -15, "min_y": -5, "max_x": 5, "max_y": 35},
            "origin": {"x": 0, "y": 30},
        }
    )

    assert spec.index_extent == (-1, 3, -2, 0)
    assert spec.cell_index(0, 30) == (0, 0)


def test_fractional_cell_edges_do_not_accumulate_binary_float_error() -> None:
    spec = GridSpec.from_mapping(
        {
            "crs": "EPSG:3857",
            "cell_size": 0.1,
            "bounds": {"min_x": 0, "min_y": 0, "max_x": 0.3, "max_y": 0.3},
            "origin": {"x": 0, "y": 0.3},
        }
    )

    grid = create_grid(spec)

    assert grid.iloc[2]["right"] == 0.3
    assert grid.iloc[-1]["bottom"] == 0.0


def test_point_boundaries_use_east_and_south_cells() -> None:
    spec = example_spec()

    assert spec.cell_index(10, 25) == (0, 1)
    assert spec.cell_index(5, 20) == (1, 0)
    assert spec.cell_index(23, 25) == (0, 2)
    assert spec.cell_index(30.000001, 25) is None
    assert spec.cell_index(5, 0) is None


def test_boundary_tolerance_snaps_near_grid_lines() -> None:
    spec = GridSpec.from_mapping(
        {
            "crs": "EPSG:3826",
            "cell_size": 10,
            "bounds": {"min_x": 0, "min_y": 0, "max_x": 20, "max_y": 20},
            "origin": {"x": 0, "y": 20},
            "boundary_tolerance": 0.001,
        }
    )

    assert spec.cell_index(9.9995, 10.0005) == (1, 1)


@pytest.mark.parametrize(
    "update",
    [
        {"cell_size": 0},
        {"cell_size": -1},
        {"crs": "not-a-crs"},
        {"bounds": {"min_x": 1, "min_y": 0, "max_x": 1, "max_y": 2}},
        {"origin": {"x": float("nan"), "y": 0}},
        {"unexpected": True},
    ],
)
def test_invalid_grid_specification_is_rejected(update: dict[str, object]) -> None:
    value: dict[str, object] = {
        "crs": "EPSG:3826",
        "cell_size": 10,
        "bounds": {"min_x": 0, "min_y": 0, "max_x": 20, "max_y": 20},
        "origin": {"x": 0, "y": 20},
    }
    value.update(update)

    with pytest.raises(GridSpecError):
        GridSpec.from_mapping(value)
