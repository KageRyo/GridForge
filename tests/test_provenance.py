from __future__ import annotations

import json
import os
import stat
from datetime import datetime

import pytest

from gridforge import __version__
from gridforge.grid.build import create_grid
from gridforge.grid.spec import GridSpec
from gridforge.provenance import write_provenance


def test_provenance_records_spatial_operation_and_grid_identity(tmp_path) -> None:
    grid = create_grid(
        GridSpec.from_mapping(
            {
                "crs": "EPSG:3826",
                "cell_size": 20,
                "bounds": {"min_x": 0, "min_y": 0, "max_x": 40, "max_y": 40},
                "origin": {"x": 0, "y": 40},
            }
        )
    )
    output = tmp_path / "features.parquet"

    path = write_provenance(
        output,
        operation="point_alignment",
        source="stations.csv",
        grid=grid,
        parameters={"aggregation": {"rainfall": "mean"}, "source_crs": "EPSG:3826"},
    )
    value = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "features.parquet.gridforge.json"
    assert value["gridforge_version"] == __version__
    assert value["operation"] == "point_alignment"
    assert value["source"] == "stations.csv"
    assert value["grid_fingerprint"] == grid["grid_fingerprint"].iloc[0]
    assert value["grid_spec"] == grid.attrs["gridforge_spec"]
    assert value["parameters"]["aggregation"] == {"rainfall": "mean"}
    assert datetime.fromisoformat(value["created_at"].replace("Z", "+00:00")).tzinfo


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_provenance_does_not_follow_preexisting_temporary_links(tmp_path, link_kind):
    grid = create_grid(
        GridSpec.from_mapping(
            {
                "crs": "EPSG:3826",
                "cell_size": 20,
                "bounds": {"min_x": 0, "min_y": 0, "max_x": 20, "max_y": 20},
                "origin": {"x": 0, "y": 20},
            }
        )
    )
    outside = tmp_path / "outside.json"
    outside.write_text("keep outside data", encoding="utf-8")
    planted = tmp_path / ".features.parquet.gridforge.json.tmp"
    if link_kind == "symlink":
        planted.symlink_to(outside)
    else:
        os.link(outside, planted)

    sidecar = write_provenance(
        tmp_path / "features.parquet",
        operation="point_alignment",
        source="stations.csv",
        grid=grid,
        parameters={},
    )

    assert outside.read_text(encoding="utf-8") == "keep outside data"
    assert json.loads(sidecar.read_text(encoding="utf-8"))["operation"] == "point_alignment"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_sidecar_preserves_ordinary_and_existing_file_permissions(tmp_path):
    grid = create_grid(
        GridSpec.from_mapping(
            {
                "crs": "EPSG:3826",
                "cell_size": 20,
                "bounds": {"min_x": 0, "min_y": 0, "max_x": 20, "max_y": 20},
                "origin": {"x": 0, "y": 20},
            }
        )
    )
    reference = tmp_path / "ordinary"
    reference.write_bytes(b"reference")
    output = tmp_path / "features.parquet"
    arguments = {
        "operation": "point_alignment",
        "source": "stations.csv",
        "grid": grid,
        "parameters": {},
    }

    sidecar = write_provenance(output, **arguments)
    assert stat.S_IMODE(sidecar.stat().st_mode) == stat.S_IMODE(reference.stat().st_mode)
    for mode in (0o640, 0o2640):
        sidecar.chmod(mode)
        write_provenance(output, **arguments)
        assert stat.S_IMODE(sidecar.stat().st_mode) == 0o640
