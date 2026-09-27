"""Domain exceptions raised by GridForge."""


class GridForgeError(Exception):
    """Base class for expected GridForge errors."""


class GridSpecError(GridForgeError, ValueError):
    """A canonical grid specification is invalid."""


class DatasetError(GridForgeError, ValueError):
    """An input or output dataset violates its declared contract."""
