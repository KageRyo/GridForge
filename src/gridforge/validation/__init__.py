"""Validation API for canonical grids and aligned datasets."""

from gridforge.validation.dataset import validate_dataset, validate_grid
from gridforge.validation.report import ValidationFinding, ValidationReport

__all__ = [
    "ValidationFinding",
    "ValidationReport",
    "validate_dataset",
    "validate_grid",
]
