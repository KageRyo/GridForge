from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest

from gridforge.grid.build import create_grid
from gridforge.grid.spec import GridSpec
from gridforge.validation import validate_dataset, validate_grid


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


def test_valid_grid_has_pass_report_and_json_contract() -> None:
    report = validate_grid(grid())

    assert report.status == "PASS"
    assert report.exit_code == 0
    assert report.to_dict()["status"] == "PASS"
    assert report.to_dict()["findings"] == []


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("duplicate", "duplicate_grid_ids"),
        ("missing", "missing_grid_ids"),
        ("extra", "unexpected_grid_ids"),
        ("unsorted", "grid_order"),
        ("bad_geometry", "invalid_geometry"),
        ("wrong_fingerprint", "grid_fingerprint"),
        ("outside", "outside_extent"),
        ("invalid_index", "invalid_grid_indices"),
    ],
)
def test_grid_validator_reports_structural_errors(mutation, code) -> None:
    value = grid()
    if mutation == "duplicate":
        value.loc[value.index[0], "grid_id"] = value.iloc[1]["grid_id"]
    elif mutation == "missing":
        value = value.iloc[1:].copy()
    elif mutation == "extra":
        value.loc[value.index[0], "grid_id"] = "99:99"
    elif mutation == "unsorted":
        value = value.iloc[::-1].copy()
    elif mutation == "bad_geometry":
        value.loc[value.index[0], "geometry"] = None
    elif mutation == "wrong_fingerprint":
        value.loc[value.index[0], "grid_fingerprint"] = "bad"
    elif mutation == "outside":
        value.loc[value.index[0], "left"] = -10.0
    elif mutation == "invalid_index":
        value.loc[value.index[0], "row"] = None

    report = validate_grid(value)

    assert report.status == "ERROR"
    assert report.exit_code == 2
    assert code in {finding.code for finding in report.findings}


def test_dataset_validator_compares_grid_and_reports_nulls_and_bad_coverage() -> None:
    canonical = grid()
    dataset = canonical.copy()
    dataset["temperature"] = [1.0, np.nan, 3.0, 4.0]
    dataset["landuse_coverage_ratio"] = [0.2, 0.0, 1.2, 0.5]

    report = validate_dataset(dataset, grid=canonical)

    assert report.status == "ERROR"
    assert report.exit_code == 2
    codes = {finding.code for finding in report.findings}
    assert "coverage_ratio" in codes
    assert "null_values" in codes
    assert any(finding.severity == "WARNING" for finding in report.findings)


def test_dataset_validator_finds_missing_cells_and_grid_mismatch() -> None:
    canonical = grid()
    missing = canonical.iloc[:-1].copy()
    report = validate_dataset(missing, grid=canonical)
    assert "missing_grid_ids" in {finding.code for finding in report.findings}

    shifted = create_grid(
        GridSpec.from_mapping(
            {
                "crs": "EPSG:3826",
                "cell_size": 10,
                "bounds": {"min_x": 100, "min_y": 0, "max_x": 120, "max_y": 20},
                "origin": {"x": 100, "y": 20},
            }
        )
    )
    mismatch = validate_dataset(shifted, grid=canonical)
    assert "grid_fingerprint_mismatch" in {finding.code for finding in mismatch.findings}


def test_dataset_validator_flags_nonfinite_values_and_crs_mismatch() -> None:
    canonical = grid()
    dataset = canonical.copy()
    dataset["score"] = [1.0, np.inf, 3.0, 4.0]
    dataset = dataset.set_crs("EPSG:4326", allow_override=True)

    report = validate_dataset(dataset, grid=canonical)

    codes = {finding.code for finding in report.findings}
    assert "crs_mismatch" in codes
    assert "nonfinite_values" in codes


def test_dataset_validator_reports_invalid_comparison_grid_without_crashing() -> None:
    canonical = grid()
    dataset = canonical.copy()
    invalid_grid = canonical.copy()
    invalid_grid.loc[invalid_grid.index[0], "grid_id"] = invalid_grid.iloc[1]["grid_id"]

    report = validate_dataset(dataset, grid=invalid_grid)

    assert "duplicate_grid_ids" in {finding.code for finding in report.findings}
