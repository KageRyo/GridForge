"""Validated, deterministic canonical grid specifications."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml
from pyproj import CRS

from gridforge.errors import GridSpecError

_SPEC_KEYS = {"crs", "cell_size", "bounds", "origin", "boundary_tolerance"}
_BOUND_KEYS = {"min_x", "min_y", "max_x", "max_y"}
_ORIGIN_KEYS = {"x", "y"}


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise GridSpecError(f"{label} must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise GridSpecError(f"{label} must be a finite number") from None
    if not result.is_finite():
        raise GridSpecError(f"{label} must be a finite number")
    return result


def _text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


def _floor(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _ceil(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def _require_mapping(value: Any, label: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GridSpecError(f"{label} must be a mapping")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise GridSpecError(f"unknown {label} key(s): {', '.join(unknown)}")
    return value


@dataclass(frozen=True)
class Bounds:
    min_x: Decimal
    min_y: Decimal
    max_x: Decimal
    max_y: Decimal


@dataclass(frozen=True)
class Origin:
    x: Decimal
    y: Decimal


@dataclass(frozen=True)
class GridSpec:
    """A square grid anchored to an explicit top-left cell-corner origin.

    Coordinates and ``cell_size`` use the units of the projected CRS. Row
    indices increase south and column indices increase east. Requested bounds
    include every cell with positive-area overlap, expanding out to cell edges.
    """

    crs: CRS
    cell_size: Decimal
    bounds: Bounds
    origin: Origin
    boundary_tolerance: Decimal = Decimal("1e-9")

    @classmethod
    def from_yaml(cls, path: str | Path) -> GridSpec:
        """Load a grid specification from a YAML file."""
        try:
            value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise GridSpecError(f"cannot read grid specification {path}: {exc}") from exc
        return cls.from_mapping(value)

    @classmethod
    def from_mapping(cls, value: Any) -> GridSpec:
        """Parse and validate a mapping with explicit CRS, bounds, and origin."""
        data = _require_mapping(value, "grid specification", _SPEC_KEYS)
        missing = sorted(_SPEC_KEYS - {"boundary_tolerance"} - set(data))
        if missing:
            raise GridSpecError(f"missing grid specification key(s): {', '.join(missing)}")

        try:
            crs = CRS.from_user_input(data["crs"])
        except Exception as exc:
            raise GridSpecError(f"invalid CRS: {data['crs']!r}") from exc
        if not crs.is_projected:
            raise GridSpecError("canonical grid CRS must be projected")

        cell_size = _decimal(data["cell_size"], "cell_size")
        if cell_size <= 0:
            raise GridSpecError("cell_size must be greater than zero")

        bounds_data = _require_mapping(data["bounds"], "bounds", _BOUND_KEYS)
        origin_data = _require_mapping(data["origin"], "origin", _ORIGIN_KEYS)
        if set(bounds_data) != _BOUND_KEYS:
            raise GridSpecError("bounds must define min_x, min_y, max_x, and max_y")
        if set(origin_data) != _ORIGIN_KEYS:
            raise GridSpecError("origin must define x and y")

        bounds = Bounds(**{key: _decimal(bounds_data[key], f"bounds.{key}") for key in _BOUND_KEYS})
        origin = Origin(
            x=_decimal(origin_data["x"], "origin.x"),
            y=_decimal(origin_data["y"], "origin.y"),
        )
        if bounds.min_x >= bounds.max_x or bounds.min_y >= bounds.max_y:
            raise GridSpecError("bounds must have positive width and height")

        tolerance = _decimal(data.get("boundary_tolerance", "1e-9"), "boundary_tolerance")
        if tolerance < 0 or tolerance * 2 >= cell_size:
            raise GridSpecError("boundary_tolerance must be nonnegative and less than half a cell")

        return cls(crs, cell_size, bounds, origin, tolerance)

    @property
    def crs_id(self) -> str:
        """Return a stable authority identifier or normalized WKT for the CRS."""
        authority = self.crs.to_authority()
        if authority:
            return f"{authority[0]}:{authority[1]}"
        return self.crs.to_wkt(version="WKT2_2019", pretty=False)

    @property
    def index_extent(self) -> tuple[int, int, int, int]:
        """Return inclusive ``(row_start, row_end, col_start, col_end)``."""
        row_start = _floor((self.origin.y - self.bounds.max_y) / self.cell_size)
        row_end = _ceil((self.origin.y - self.bounds.min_y) / self.cell_size) - 1
        col_start = _floor((self.bounds.min_x - self.origin.x) / self.cell_size)
        col_end = _ceil((self.bounds.max_x - self.origin.x) / self.cell_size) - 1
        return row_start, row_end, col_start, col_end

    @property
    def fingerprint(self) -> str:
        """Hash the normalized CRS, grid spacing, origin, and indexed extent."""
        row_start, row_end, col_start, col_end = self.index_extent
        identity = {
            "cell_size": _text(self.cell_size),
            "col_extent": [col_start, col_end],
            "crs": self.crs_id,
            "origin": [_text(self.origin.x), _text(self.origin.y)],
            "row_extent": [row_start, row_end],
            "schema": "gridforge-grid-v1",
        }
        canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def cell_index(self, x: float, y: float) -> tuple[int, int] | None:
        """Return the containing ``(row, column)`` or ``None`` outside the grid.

        Cells use ``[left, right) × (bottom, top]``. Coordinates within the
        configured tolerance of an anchored grid line are snapped to that line.
        """
        try:
            x_value = _decimal(x, "x")
            y_value = _decimal(y, "y")
        except GridSpecError:
            return None
        col_position = (x_value - self.origin.x) / self.cell_size
        row_position = (self.origin.y - y_value) / self.cell_size
        col_position = self._snap_index(col_position)
        row_position = self._snap_index(row_position)
        column = int(col_position.to_integral_value(rounding=ROUND_FLOOR))
        row = int(row_position.to_integral_value(rounding=ROUND_FLOOR))
        row_start, row_end, col_start, col_end = self.index_extent
        if row_start <= row <= row_end and col_start <= column <= col_end:
            return row, column
        return None

    def _snap_index(self, value: Decimal) -> Decimal:
        nearest = value.to_integral_value(rounding=ROUND_HALF_UP)
        if abs(value - nearest) * self.cell_size <= self.boundary_tolerance:
            return nearest
        return value

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible normalized grid specification metadata."""
        return {
            "crs": self.crs_id,
            "cell_size": _text(self.cell_size),
            "bounds": {
                "min_x": _text(self.bounds.min_x),
                "min_y": _text(self.bounds.min_y),
                "max_x": _text(self.bounds.max_x),
                "max_y": _text(self.bounds.max_y),
            },
            "origin": {"x": _text(self.origin.x), "y": _text(self.origin.y)},
            "boundary_tolerance": _text(self.boundary_tolerance),
        }
