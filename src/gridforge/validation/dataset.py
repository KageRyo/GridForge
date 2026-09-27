"""Grid and aligned-dataset contract validation."""

from __future__ import annotations

from typing import Literal

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from gridforge.grid.build import get_grid_spec
from gridforge.validation.report import ValidationFinding, ValidationReport

_REQUIRED_GRID_COLUMNS = {
    "grid_id",
    "grid_fingerprint",
    "row",
    "column",
    "left",
    "bottom",
    "right",
    "top",
    "geometry",
}
_SPATIAL_COLUMNS = _REQUIRED_GRID_COLUMNS


def _append(
    findings: list[ValidationFinding],
    severity: Literal["ERROR", "WARNING"],
    code: str,
    message: str,
    count: int | None = None,
) -> None:
    findings.append(ValidationFinding(severity, code, message, count))


def _grid_structure(grid: gpd.GeoDataFrame, findings: list[ValidationFinding]) -> None:
    missing_columns = sorted(_REQUIRED_GRID_COLUMNS - set(grid.columns))
    if missing_columns:
        _append(
            findings,
            "ERROR",
            "required_columns",
            f"grid is missing required columns: {', '.join(missing_columns)}",
        )
        return
    if grid.empty:
        _append(findings, "ERROR", "empty_grid", "grid must contain at least one cell")
        return
    if grid.crs is None:
        _append(findings, "ERROR", "unknown_crs", "grid CRS is unknown")

    if grid["grid_id"].isna().any():
        _append(
            findings,
            "ERROR",
            "null_grid_ids",
            "grid IDs must be non-null",
            int(grid["grid_id"].isna().sum()),
        )
    duplicates = int(grid["grid_id"].duplicated().sum())
    if duplicates:
        _append(
            findings,
            "ERROR",
            "duplicate_grid_ids",
            "grid contains duplicate grid IDs",
            duplicates,
        )

    row_values = pd.to_numeric(grid["row"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    column_values = pd.to_numeric(grid["column"], errors="coerce").to_numpy(
        dtype=float, na_value=np.nan
    )
    valid_indexes = (
        np.isfinite(row_values)
        & np.isfinite(column_values)
        & (row_values == np.floor(row_values))
        & (column_values == np.floor(column_values))
    )
    invalid_indexes = int((~valid_indexes).sum())
    if invalid_indexes:
        _append(
            findings,
            "ERROR",
            "invalid_grid_indices",
            "grid row and column indices must be finite integers",
            invalid_indexes,
        )

    try:
        spec = get_grid_spec(grid)
    except Exception as exc:
        code = "crs_mismatch" if "grid CRS does not match" in str(exc) else "grid_fingerprint"
        _append(findings, "ERROR", code, f"grid specification is invalid: {exc}")
        return

    expected_fingerprint = spec.fingerprint
    fingerprint_mismatch = int(
        grid["grid_fingerprint"].isna().sum()
        + (~grid["grid_fingerprint"].astype(str).eq(expected_fingerprint)).sum()
    )
    if fingerprint_mismatch:
        _append(
            findings,
            "ERROR",
            "grid_fingerprint",
            "grid rows do not match the specification fingerprint",
            fingerprint_mismatch,
        )

    row_start, row_end, col_start, col_end = spec.index_extent
    expected_ids = {
        f"{row}:{column}"
        for row in range(row_start, row_end + 1)
        for column in range(col_start, col_end + 1)
    }
    observed_ids = set(grid["grid_id"].dropna().astype(str))
    missing_ids = sorted(expected_ids - observed_ids)
    extra_ids = sorted(observed_ids - expected_ids)
    if missing_ids:
        _append(
            findings,
            "ERROR",
            "missing_grid_ids",
            "grid is missing canonical grid IDs",
            len(missing_ids),
        )
    if extra_ids:
        _append(
            findings,
            "ERROR",
            "unexpected_grid_ids",
            "grid contains unexpected grid IDs outside its canonical extent",
            len(extra_ids),
        )

    safe_rows = np.where(np.isfinite(row_values), row_values, np.inf)
    safe_columns = np.where(np.isfinite(column_values), column_values, np.inf)
    order = np.lexsort((safe_columns, safe_rows))
    if not np.array_equal(order, np.arange(len(grid))):
        _append(findings, "ERROR", "grid_order", "grid rows are not sorted by row and column")

    outside_count = 0
    invalid_geometry_count = 0
    geometry_mismatch_count = 0
    bounds_mismatch_count = 0
    expected_min_x = float(spec.origin.x + col_start * spec.cell_size)
    expected_max_x = float(spec.origin.x + (col_end + 1) * spec.cell_size)
    expected_min_y = float(spec.origin.y - (row_end + 1) * spec.cell_size)
    expected_max_y = float(spec.origin.y - row_start * spec.cell_size)
    expected_extent = (expected_min_x, expected_min_y, expected_max_x, expected_max_y)
    for position, record in enumerate(grid.itertuples(index=False)):
        if not valid_indexes[position]:
            outside_count += 1
            continue
        row = int(row_values[position])
        column = int(column_values[position])
        tolerance = float(spec.boundary_tolerance)
        try:
            actual_bounds = tuple(
                float(value) for value in (record.left, record.bottom, record.right, record.top)
            )
        except (TypeError, ValueError):
            actual_bounds = (np.nan, np.nan, np.nan, np.nan)
        valid_bounds = bool(np.isfinite(actual_bounds).all())
        if not valid_bounds:
            outside_count += 1
            bounds_mismatch_count += 1
        elif (
            not (row_start <= row <= row_end and col_start <= column <= col_end)
            or actual_bounds[0] < expected_extent[0] - tolerance
            or actual_bounds[2] > expected_extent[2] + tolerance
            or actual_bounds[1] < expected_extent[1] - tolerance
            or actual_bounds[3] > expected_extent[3] + tolerance
        ):
            outside_count += 1
        if str(record.grid_id) != f"{row}:{column}":
            geometry_mismatch_count += 1
        geometry = record.geometry
        if geometry is None or geometry.is_empty or not geometry.is_valid:
            invalid_geometry_count += 1
            continue
        expected_left = float(spec.origin.x + column * spec.cell_size)
        expected_right = float(spec.origin.x + (column + 1) * spec.cell_size)
        expected_top = float(spec.origin.y - row * spec.cell_size)
        expected_bottom = float(spec.origin.y - (row + 1) * spec.cell_size)
        expected_geometry = box(expected_left, expected_bottom, expected_right, expected_top)
        if not geometry.equals(expected_geometry):
            geometry_mismatch_count += 1
        if valid_bounds:
            for actual, expected in zip(
                actual_bounds,
                (expected_left, expected_bottom, expected_right, expected_top),
                strict=True,
            ):
                if not np.isclose(actual, expected, rtol=0.0, atol=tolerance):
                    bounds_mismatch_count += 1
                    break
    if outside_count:
        _append(
            findings,
            "ERROR",
            "outside_extent",
            "grid contains cells outside its canonical extent",
            outside_count,
        )
    if invalid_geometry_count:
        _append(
            findings,
            "ERROR",
            "invalid_geometry",
            "grid contains null, empty, or invalid cell geometry",
            invalid_geometry_count,
        )
    if geometry_mismatch_count:
        _append(
            findings,
            "ERROR",
            "cell_geometry_mismatch",
            "grid IDs or geometries do not match canonical row and column indices",
            geometry_mismatch_count,
        )
    if bounds_mismatch_count:
        _append(
            findings,
            "ERROR",
            "cell_bounds_mismatch",
            "cell bounds do not match canonical row and column indices",
            bounds_mismatch_count,
        )


def _value_statistics(
    dataset: gpd.GeoDataFrame,
    findings: list[ValidationFinding],
) -> None:
    for column in dataset.columns:
        if column in _SPATIAL_COLUMNS:
            continue
        values = dataset[column]
        null_count = int(values.isna().sum())
        if null_count:
            _append(
                findings,
                "WARNING",
                "null_values",
                f"column {column!r} contains null or nodata values",
                null_count,
            )
        if "coverage_ratio" in column:
            try:
                numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
            except (TypeError, ValueError):
                numeric = np.full(len(values), np.nan)
            invalid = (~np.isfinite(numeric)) | (numeric < -1e-9) | (numeric > 1.0 + 1e-9)
            if invalid.any():
                _append(
                    findings,
                    "ERROR",
                    "coverage_ratio",
                    f"column {column!r} contains null, non-finite, or out-of-range coverage ratios",
                    int(invalid.sum()),
                )
        if pd.api.types.is_numeric_dtype(values.dtype):
            try:
                numeric = values.to_numpy(dtype=float, na_value=np.nan)
                nonfinite = (~np.isfinite(numeric)) & (~np.isnan(numeric))
            except (TypeError, ValueError):
                continue
            if nonfinite.any():
                _append(
                    findings,
                    "ERROR",
                    "nonfinite_values",
                    f"column {column!r} contains infinite values",
                    int(nonfinite.sum()),
                )


def validate_grid(grid: gpd.GeoDataFrame) -> ValidationReport:
    """Validate a canonical grid and return structured findings."""
    findings: list[ValidationFinding] = []
    if not isinstance(grid, gpd.GeoDataFrame):
        _append(findings, "ERROR", "not_geodataframe", "grid must be a GeoDataFrame")
        return ValidationReport(tuple(findings))
    _grid_structure(grid, findings)
    return ValidationReport(tuple(findings))


def validate_dataset(
    dataset: gpd.GeoDataFrame,
    *,
    grid: gpd.GeoDataFrame | None = None,
) -> ValidationReport:
    """Validate one complete aligned dataset, optionally against a canonical grid."""
    findings: list[ValidationFinding] = []
    if not isinstance(dataset, gpd.GeoDataFrame):
        _append(findings, "ERROR", "not_geodataframe", "dataset must be a GeoDataFrame")
        return ValidationReport(tuple(findings))
    _grid_structure(dataset, findings)
    if grid is not None:
        if not isinstance(grid, gpd.GeoDataFrame):
            _append(findings, "ERROR", "invalid_grid", "comparison grid must be a GeoDataFrame")
        else:
            grid_report = validate_grid(grid)
            findings.extend(grid_report.findings)
            if dataset.crs is None or grid.crs is None or not dataset.crs.equals(grid.crs):
                _append(
                    findings,
                    "ERROR",
                    "crs_mismatch",
                    "dataset CRS does not match canonical grid CRS",
                )
            dataset_fingerprints = set(
                dataset.get("grid_fingerprint", pd.Series(dtype=str)).dropna().astype(str)
            )
            grid_fingerprints = set(
                grid.get("grid_fingerprint", pd.Series(dtype=str)).dropna().astype(str)
            )
            if dataset_fingerprints != grid_fingerprints or len(grid_fingerprints) != 1:
                _append(
                    findings,
                    "ERROR",
                    "grid_fingerprint_mismatch",
                    "dataset grid fingerprint does not match canonical grid",
                )
            if grid_report.exit_code == 0 and "grid_id" in dataset and "grid_id" in grid:
                if dataset["grid_id"].duplicated().any():
                    pass
                else:
                    expected = set(grid["grid_id"].dropna().astype(str))
                    observed = set(dataset["grid_id"].dropna().astype(str))
                    missing = expected - observed
                    extra = observed - expected
                    if missing:
                        _append(
                            findings,
                            "ERROR",
                            "missing_grid_ids",
                            "dataset is missing grid IDs from the canonical grid",
                            len(missing),
                        )
                    if extra:
                        _append(
                            findings,
                            "ERROR",
                            "unexpected_grid_ids",
                            "dataset contains grid IDs outside the canonical grid",
                            len(extra),
                        )
                    if not missing and not extra:
                        expected_by_id = grid.set_index("grid_id")
                        actual_by_id = dataset.set_index("grid_id")
                        mismatch_count = 0
                        for grid_id in expected:
                            actual_geometry = actual_by_id.loc[grid_id].geometry
                            expected_geometry = expected_by_id.loc[grid_id].geometry
                            if (
                                actual_geometry is None
                                or expected_geometry is None
                                or not actual_geometry.equals(expected_geometry)
                            ):
                                mismatch_count += 1
                        if mismatch_count:
                            _append(
                                findings,
                                "ERROR",
                                "alignment_mismatch",
                                "dataset cell geometry does not match canonical grid",
                                mismatch_count,
                            )
    _value_statistics(dataset, findings)
    return ValidationReport(tuple(findings))
