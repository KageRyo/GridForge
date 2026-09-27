"""Safe feature joins for datasets sharing one canonical grid."""

from __future__ import annotations

from collections.abc import Sequence

import geopandas as gpd

from gridforge.errors import DatasetError
from gridforge.validation import validate_dataset, validate_grid

_GRID_COLUMNS = {
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


def _require_valid(report, label: str) -> None:
    errors = [finding for finding in report.findings if finding.severity == "ERROR"]
    if errors:
        details = "; ".join(finding.message for finding in errors[:3])
        if any(finding.code == "grid_fingerprint_mismatch" for finding in errors):
            raise DatasetError(f"{label} grid fingerprint mismatch: {details}")
        if any(finding.code == "crs_mismatch" for finding in errors) or (
            "CRS does not match" in details
        ):
            raise DatasetError(f"{label} CRS mismatch: {details}")
        if any(
            finding.code in {"cell_geometry_mismatch", "alignment_mismatch"} for finding in errors
        ):
            raise DatasetError(f"{label} geometry mismatch: {details}")
        raise DatasetError(f"{label} is invalid: {details}")


def join_features(
    grid: gpd.GeoDataFrame,
    *features: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Join complete aligned feature frames after verifying grid identity."""
    _require_valid(validate_grid(grid), "canonical grid")
    result = grid.copy()
    seen: set[str] = set()
    for index, feature in enumerate(features, start=1):
        if isinstance(feature, gpd.GeoDataFrame) and {"row", "column"} <= set(feature.columns):
            feature = feature.sort_values(["row", "column"], kind="stable")
        _require_valid(validate_dataset(feature, grid=grid), f"feature dataset {index}")
        columns: Sequence[str] = [
            column for column in feature.columns if column not in _GRID_COLUMNS
        ]
        duplicates = sorted(seen.intersection(columns))
        if duplicates:
            raise DatasetError(
                f"duplicate feature columns across aligned datasets: {', '.join(duplicates)}"
            )
        seen.update(columns)
        if columns:
            attributes = feature[["grid_id", *columns]]
            result = result.merge(
                attributes,
                on="grid_id",
                how="left",
                sort=False,
                validate="one_to_one",
            )
    result = result.sort_values(["row", "column"], kind="stable").reset_index(drop=True)
    result.attrs["gridforge_spec"] = grid.attrs.get("gridforge_spec")
    _require_valid(validate_dataset(result, grid=grid), "joined dataset")
    return result
