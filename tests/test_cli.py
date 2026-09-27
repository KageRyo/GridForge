import json

import geopandas as gpd
import numpy as np
import rasterio
from affine import Affine
from shapely.geometry import box
from typer.testing import CliRunner

from gridforge.cli import app
from gridforge.grid.build import create_grid
from gridforge.grid.spec import GridSpec
from gridforge.io.grid import write_grid


def test_help_is_available() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.stdout
    for command in ("inspect", "grid", "align", "join", "validate", "demo"):
        assert command in result.stdout


def test_version_is_available() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_cli_build_align_join_and_validate_workflow(tmp_path) -> None:
    runner = CliRunner()
    spec_path = tmp_path / "grid.yaml"
    spec_path.write_text(
        """crs: EPSG:3857
cell_size: 10
bounds:
  min_x: 0
  min_y: 0
  max_x: 20
  max_y: 20
origin:
  x: 0
  y: 20
""",
        encoding="utf-8",
    )
    grid_path = tmp_path / "grid.parquet"
    result = runner.invoke(app, ["grid", "create", str(spec_path), "--output", str(grid_path)])
    assert result.exit_code == 0, result.output

    points_path = tmp_path / "points.csv"
    points_path.write_text("x,y,rainfall\n5,15,10\n15,5,30\n", encoding="utf-8")
    points_output = tmp_path / "points.parquet"
    result = runner.invoke(
        app,
        [
            "align",
            "points",
            str(points_path),
            "--grid",
            str(grid_path),
            "--source-crs",
            "EPSG:3857",
            "--value",
            "rainfall",
            "--agg",
            "mean",
            "--output",
            str(points_output),
        ],
    )
    assert result.exit_code == 0, result.output

    vector_path = tmp_path / "areas.geojson"
    gpd.GeoDataFrame(
        {"kind": ["left", "right"], "score": [2.0, 8.0]},
        geometry=[box(0, 0, 10, 20), box(10, 0, 20, 20)],
        crs="EPSG:3857",
    ).to_file(vector_path, driver="GeoJSON")
    vector_output = tmp_path / "areas.parquet"
    result = runner.invoke(
        app,
        [
            "align",
            "vector",
            str(vector_path),
            "--grid",
            str(grid_path),
            "--category",
            "kind",
            "--numeric-column",
            "score",
            "--output",
            str(vector_output),
        ],
    )
    assert result.exit_code == 0, result.output

    raster_path = tmp_path / "values.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=Affine.translation(0, 20) @ Affine.scale(10, -10),
        nodata=-9999,
    ) as raster:
        raster.write(np.array([[1, 2], [3, 4]], dtype="float32"), 1)
    raster_output = tmp_path / "values.parquet"
    result = runner.invoke(
        app,
        [
            "align",
            "raster",
            str(raster_path),
            "--grid",
            str(grid_path),
            "--agg",
            "mean",
            "--output",
            str(raster_output),
        ],
    )
    assert result.exit_code == 0, result.output

    features_path = tmp_path / "features.parquet"
    result = runner.invoke(
        app,
        [
            "join",
            str(grid_path),
            str(points_output),
            str(vector_output),
            str(raster_output),
            "--output",
            str(features_path),
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        ["validate", str(features_path), "--grid", str(grid_path), "--json"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "WARNING"

    shifted_spec = GridSpec.from_mapping(
        {
            "crs": "EPSG:3857",
            "cell_size": 10,
            "bounds": {"min_x": 100, "min_y": 0, "max_x": 120, "max_y": 20},
            "origin": {"x": 100, "y": 20},
        }
    )
    shifted_path = tmp_path / "shifted.parquet"
    write_grid(create_grid(shifted_spec), shifted_path)
    result = runner.invoke(
        app,
        ["validate", str(features_path), "--grid", str(shifted_path), "--json"],
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)["status"] == "ERROR"


def test_inspect_rejects_unknown_crs_for_coordinate_table(tmp_path) -> None:
    source = tmp_path / "points.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["inspect", str(source)])

    assert result.exit_code == 2
    assert "source CRS is unknown" in result.output


def test_demo_runs_entirely_from_synthetic_inputs(tmp_path) -> None:
    output = tmp_path / "demo"

    result = CliRunner().invoke(app, ["demo", "--output-dir", str(output)])

    assert result.exit_code == 0, result.output
    assert (output / "features.parquet").exists()
    assert (output / "features.parquet.gridforge.json").exists()
    assert "Demo complete" in result.output
