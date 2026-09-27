"""Lightweight metadata for reproducible spatial transformations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd

from gridforge import __version__
from gridforge.errors import DatasetError
from gridforge.grid.spec import GridSpec


def write_provenance(
    output_path: str | Path,
    *,
    operation: str,
    source: str | list[str] | tuple[str, ...],
    grid: gpd.GeoDataFrame,
    parameters: dict[str, Any],
) -> Path:
    """Write a concise JSON sidecar describing one spatial transformation.

    The sidecar records transformation inputs and policy, not source hashes,
    full lineage, immutable release state, or artifact integrity.
    """
    spec_value = grid.attrs.get("gridforge_spec")
    if not isinstance(spec_value, dict):
        raise DatasetError("grid is missing GridForge specification metadata")
    try:
        spec = GridSpec.from_mapping(spec_value)
    except ValueError as exc:
        raise DatasetError(f"grid specification metadata is invalid: {exc}") from exc
    fingerprints = grid.get("grid_fingerprint")
    if fingerprints is None or fingerprints.empty:
        raise DatasetError("grid is missing GridForge fingerprint")
    fingerprint = str(fingerprints.iloc[0])
    if fingerprint != spec.fingerprint or not fingerprints.astype(str).eq(fingerprint).all():
        raise DatasetError("grid fingerprint does not match GridForge specification")

    output = Path(output_path)
    sidecar = Path(f"{output}.gridforge.json")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    source_crs = parameters.get("source_crs")
    record = {
        "gridforge_version": __version__,
        "operation": operation,
        "source": source,
        "source_crs": source_crs,
        "target_crs": spec.crs_id,
        "grid_fingerprint": fingerprint,
        "grid_spec": spec.to_dict(),
        "parameters": parameters,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "output": output.name,
    }
    temporary = sidecar.with_name(f".{sidecar.name}.tmp")
    try:
        serialized = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        temporary.write_text(
            serialized + "\n",
            encoding="utf-8",
        )
        temporary.replace(sidecar)
    except (OSError, TypeError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        raise DatasetError(f"cannot write valid provenance sidecar {sidecar}: {exc}") from exc
    return sidecar
