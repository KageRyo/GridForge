from __future__ import annotations

import pandas.testing as pd_testing

from gridforge.demo import run_demo
from gridforge.io.datasets import read_dataset


def test_synthetic_demo_is_repeatable_and_complete(tmp_path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first_report = run_demo(first_dir)
    second_report = run_demo(second_dir)
    first = read_dataset(first_dir / "features.parquet")
    second = read_dataset(second_dir / "features.parquet")

    assert first_report.exit_code == second_report.exit_code == 0
    assert len(first) == 16
    expected_ids = [f"{row}:{column}" for row in range(4) for column in range(4)]
    assert first["grid_id"].tolist() == expected_ids
    assert first.crs == second.crs
    assert first.geometry.equals(second.geometry)
    pd_testing.assert_frame_equal(
        first.drop(columns="geometry"),
        second.drop(columns="geometry"),
        check_exact=True,
    )
