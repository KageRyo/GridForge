from __future__ import annotations

import json
from datetime import datetime

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
    assert value["gridforge_version"] == "0.1.0"
    assert value["operation"] == "point_alignment"
    assert value["source"] == "stations.csv"
    assert value["grid_fingerprint"] == grid["grid_fingerprint"].iloc[0]
    assert value["grid_spec"] == grid.attrs["gridforge_spec"]
    assert value["parameters"]["aggregation"] == {"rainfall": "mean"}
    assert datetime.fromisoformat(value["created_at"].replace("Z", "+00:00")).tzinfo
