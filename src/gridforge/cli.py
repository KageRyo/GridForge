"""Command-line entry point for GridForge."""

# Typer expresses command parameters using function-call defaults.
# ruff: noqa: B008

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import typer
from pyproj import CRS

from gridforge import __version__
from gridforge.align.points import align_points
from gridforge.align.raster import align_raster
from gridforge.align.vector import align_polygons
from gridforge.demo import run_demo
from gridforge.errors import GridForgeError
from gridforge.grid.build import create_grid
from gridforge.grid.spec import GridSpec
from gridforge.io.datasets import (
    _crs_label,
    inspect_dataset,
    load_points,
    load_vector,
    read_dataset,
    write_dataset,
)
from gridforge.io.grid import read_grid, write_grid
from gridforge.join import join_features
from gridforge.provenance import write_provenance
from gridforge.validation import validate_dataset

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Build, align, join, and validate spatial grid datasets.",
)
grid_app = typer.Typer(no_args_is_help=True, help="Create canonical grids.")
align_app = typer.Typer(no_args_is_help=True, help="Align source data to a canonical grid.")
app.add_typer(grid_app, name="grid")
app.add_typer(align_app, name="align")


def _show_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_show_version,
        is_eager=True,
        help="Show the installed GridForge version and exit.",
    ),
) -> None:
    """Create and validate deterministic grid-based spatial datasets."""


def _run(action):
    try:
        return action()
    except (GridForgeError, OSError) as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=2) from exc


def _crs_arg(crs: Any) -> str | None:
    if crs is None:
        return None
    return _crs_label(CRS.from_user_input(crs))


def _print_json(value: Any) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _write_aligned(
    dataset: gpd.GeoDataFrame,
    output: Path,
    *,
    operation: str,
    source: str | list[str],
    grid: gpd.GeoDataFrame,
    parameters: dict[str, Any],
) -> None:
    write_dataset(dataset, output)
    write_provenance(
        output,
        operation=operation,
        source=source,
        grid=grid,
        parameters=parameters,
    )
    typer.echo(f"Wrote {output}")
    typer.echo(f"Wrote {output}.gridforge.json")


@app.command("inspect")
def inspect_command(
    source: Path = typer.Argument(..., exists=True, readable=True),
    source_crs: str | None = typer.Option(None, "--source-crs"),
    x_column: str = typer.Option("x", "--x-column"),
    y_column: str = typer.Option("y", "--y-column"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect spatial metadata without guessing a missing source CRS."""
    info = _run(
        lambda: inspect_dataset(
            source,
            source_crs=source_crs,
            x_column=x_column,
            y_column=y_column,
        )
    )
    if json_output:
        _print_json(info.to_dict())
        return
    typer.echo(f"Path: {info.path}")
    typer.echo(f"Kind: {info.kind}")
    typer.echo(f"Geometry: {info.geometry_type or 'unknown'}")
    typer.echo(f"CRS: {info.crs}")
    typer.echo(f"Features: {info.feature_count if info.feature_count is not None else 'n/a'}")
    typer.echo(f"Bands: {info.band_count if info.band_count is not None else 'n/a'}")
    typer.echo(f"Bounds: {info.bounds if info.bounds is not None else 'n/a'}")


@grid_app.command("create")
def grid_create(
    specification: Path = typer.Argument(..., exists=True, readable=True),
    output: Path = typer.Option(..., "--output", "-o"),
) -> None:
    """Create a deterministic GeoParquet grid from a YAML specification."""

    def action() -> None:
        spec = GridSpec.from_yaml(specification)
        grid = create_grid(spec)
        write_grid(grid, output)
        write_provenance(
            output,
            operation="grid_build",
            source=str(specification),
            grid=grid,
            parameters={"grid_spec": spec.to_dict()},
        )
        typer.echo(f"Created {len(grid)} cells: {output}")
        typer.echo(f"Wrote {output}.gridforge.json")

    _run(action)


@align_app.command("points")
def align_points_command(
    source: Path = typer.Argument(..., exists=True, readable=True),
    grid_path: Path = typer.Option(..., "--grid"),
    value: str = typer.Option(..., "--value"),
    aggregation: str = typer.Option("mean", "--agg"),
    output: Path = typer.Option(..., "--output", "-o"),
    source_crs: str | None = typer.Option(None, "--source-crs"),
    x_column: str = typer.Option("x", "--x-column"),
    y_column: str = typer.Option("y", "--y-column"),
) -> None:
    """Aggregate one point attribute into canonical cells."""

    def action() -> None:
        grid = read_grid(grid_path)
        points = load_points(
            source,
            x_column=x_column,
            y_column=y_column,
            source_crs=source_crs,
        )
        result = align_points(
            points,
            grid,
            aggregations={value: aggregation},
            source_crs=source_crs,
        )
        _write_aligned(
            result,
            output,
            operation="point_alignment",
            source=str(source),
            grid=grid,
            parameters={
                "source_crs": _crs_arg(points.crs),
                "target_crs": _crs_arg(grid.crs),
                "x_column": x_column,
                "y_column": y_column,
                "aggregation": {value: aggregation},
            },
        )

    _run(action)


@align_app.command("vector")
def align_vector_command(
    source: Path = typer.Argument(..., exists=True, readable=True),
    grid_path: Path = typer.Option(..., "--grid"),
    output: Path = typer.Option(..., "--output", "-o"),
    category: str | None = typer.Option(None, "--category"),
    numeric_column: list[str] = typer.Option([], "--numeric-column"),
    source_crs: str | None = typer.Option(None, "--source-crs"),
) -> None:
    """Aggregate polygon coverage, categories, and numeric attributes."""

    def action() -> None:
        grid = read_grid(grid_path)
        vector = load_vector(source, source_crs=source_crs)
        result = align_polygons(
            vector,
            grid,
            category_column=category,
            numeric_columns=numeric_column,
            source_crs=source_crs,
        )
        _write_aligned(
            result,
            output,
            operation="vector_alignment",
            source=str(source),
            grid=grid,
            parameters={
                "source_crs": _crs_arg(vector.crs),
                "target_crs": _crs_arg(grid.crs),
                "category_column": category,
                "numeric_columns": numeric_column,
                "coverage": "union area / cell area",
                "weighted_aggregation": "intersection-area weighted mean",
            },
        )

    _run(action)


@align_app.command("raster")
def align_raster_command(
    source: Path = typer.Argument(..., exists=True, readable=True),
    grid_path: Path = typer.Option(..., "--grid"),
    aggregation: str = typer.Option(..., "--agg"),
    output: Path = typer.Option(..., "--output", "-o"),
    band: int = typer.Option(1, "--band", min=1),
    source_crs: str | None = typer.Option(None, "--source-crs"),
    resampling: str = typer.Option("nearest", "--resampling"),
    value_name: str | None = typer.Option(None, "--value-name"),
) -> None:
    """Reproject and aggregate one raster band into canonical cells."""

    def action() -> None:
        grid = read_grid(grid_path)
        result = align_raster(
            source,
            grid,
            aggregation=aggregation,
            band=band,
            source_crs=source_crs,
            resampling=resampling,
            value_name=value_name,
        )
        operation = result.attrs.get("gridforge_operation", {})
        _write_aligned(
            result,
            output,
            operation="raster_alignment",
            source=str(source),
            grid=grid,
            parameters={
                "source_crs": operation.get("source_crs"),
                "target_crs": operation.get("target_crs"),
                "band": band,
                "aggregation": aggregation,
                "aggregation_resampling": operation.get("aggregation_resampling"),
                "resampling": resampling,
                "nodata": operation.get("nodata"),
            },
        )

    _run(action)


@app.command("join")
def join_command(
    grid_path: Path = typer.Argument(..., exists=True, readable=True),
    feature_paths: list[Path] = typer.Argument(..., exists=True, readable=True),
    output: Path = typer.Option(..., "--output", "-o"),
) -> None:
    """Join aligned GeoParquet feature datasets after identity validation."""

    def action() -> None:
        grid = read_grid(grid_path)
        features = [read_dataset(path) for path in feature_paths]
        result = join_features(grid, *features)
        _write_aligned(
            result,
            output,
            operation="feature_join",
            source=[str(grid_path), *(str(path) for path in feature_paths)],
            grid=grid,
            parameters={"feature_datasets": len(features)},
        )

    _run(action)


@app.command("validate")
def validate_command(
    dataset_path: Path = typer.Argument(..., exists=True, readable=True),
    grid_path: Path | None = typer.Option(None, "--grid"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Validate one GridForge GeoParquet dataset; errors exit with status 2."""

    def action():
        dataset = read_dataset(dataset_path)
        grid = read_grid(grid_path) if grid_path is not None else None
        return validate_dataset(dataset, grid=grid)

    report = _run(action)
    if json_output:
        _print_json(report.to_dict())
    else:
        typer.echo(report.status)
        for finding in report.findings:
            count = f" ({finding.count})" if finding.count is not None else ""
            typer.echo(f"{finding.severity}: {finding.message}{count}")
    if report.exit_code:
        raise typer.Exit(code=report.exit_code)


@app.command("demo")
def demo_command(
    output_dir: Path = typer.Option(Path("gridforge-demo"), "--output-dir"),
) -> None:
    """Run a small, synthetic point/vector/raster-to-grid workflow."""
    report = _run(lambda: run_demo(output_dir))
    _print_json(report.to_dict())
    typer.echo(f"Demo complete: {output_dir.resolve()}")
