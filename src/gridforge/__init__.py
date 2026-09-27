"""Deterministic spatial grid alignment and dataset engineering."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("gridforge-spatial")
except PackageNotFoundError:  # pragma: no cover - editable/install builds provide metadata
    __version__ = "0.1.0"

__all__ = ["__version__"]
