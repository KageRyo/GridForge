# GridForge v0.1 Implementation Plan

> **For agentic workers:** Use this plan task by task with the inline execution workflow. Each task uses test-first development for behavior changes.

**Goal:** Deliver an independently installable spatial dataset engineering package with deterministic grid, point/vector/raster alignment, safe join, validation, provenance, CLI, demo, docs, and CI.

**Architecture:** Python APIs implement spatial policies over GeoPandas/Shapely/PyProj/Rasterio. A Typer CLI and file adapters call these APIs; GeoParquet carries the canonical grid fingerprint and per-cell geometry, with small JSON provenance sidecars for CLI operations.

**Tech Stack:** Python 3.11+, GeoPandas, Shapely, PyProj, Rasterio, PyArrow, NumPy, Pandas, PyYAML, Typer, pytest, Ruff, uv.

**Spec:** `docs/superpowers/specs/2026-09-27-gridforge-v0.1-design.md`; full acceptance scope is in the user-provided GridForge v0.1 task.

## Global Constraints

- No TAG-Twin imports, schemas, data, database, constants, or directory assumptions.
- Never guess CRS; accept an explicit CRS only when source metadata is absent.
- Preserve every canonical cell and explicit missingness; never promote polygon touch to full coverage.
- Use fixed-origin row/column indices, half-open point boundaries, deterministic ordering/ties, and grid fingerprints.
- Raster resampling and aggregation policies must be explicit in API behavior and provenance.
- GridForge owns spatial transformation provenance only; no full lineage or release-management system.
- Synthetic fixtures only; do not include TAG-Twin private data.
- Do not publish, push, or merge as part of this implementation.

## Review Focus

- CRS-less vector, table, and raster inputs fail unless the caller supplies `source_crs`; embedded conflicting CRS is not silently overwritten.
- Floating-point points within tolerance of a grid boundary map deterministically; exact boundaries follow the documented half-open convention.
- Polygon overlaps do not inflate unique coverage above 1, while per-feature weighted attributes remain deterministic.
- Raster nodata, partial source extent, and different resolution/CRS preserve null cells and record the chosen resampling operation.
- Joins detect same-shaped but differently anchored grids and missing/extra/duplicate grid cells before merging values.

---

### Task 1: Package foundation and CLI shell

**Files:** `pyproject.toml`, `uv.lock`, `.gitignore`, `LICENSE`, `.github/workflows/ci.yml`, `src/gridforge/__init__.py`, `src/gridforge/cli.py`, `tests/test_cli.py`.

**Interfaces:** Distribution `gridforge-spatial`; import `gridforge`; executable `gridforge`; Typer root app exported as `app`.

- [ ] Define metadata, Python `>=3.11`, runtime/dev dependencies, Ruff and pytest settings, package discovery, and CLI entry point. Keep `gridforge-spatial` as distribution name unless the user selects another available name.
- [ ] Add Apache-2.0 license and a CI workflow with lint, test matrix (Python 3.11, 3.12, 3.14), and build validation.
- [ ] Add `test_help_is_available` and `test_version_is_available`; assert root help succeeds and `--version` prints `0.1.0`. Add command-list assertions when the real commands are implemented in Task 7.
- [ ] Run `uv sync --all-groups`, verify `uv run pytest tests/test_cli.py -q` fails first for the missing app, implement the minimum Typer shell, then verify it passes.

### Task 2: Canonical grid specification and persistence

**Files:** `src/gridforge/grid/spec.py`, `src/gridforge/grid/build.py`, `src/gridforge/io/grid.py`, `src/gridforge/errors.py`, `tests/test_grid.py`, `tests/test_grid_io.py`.

**Interfaces:** `GridSpec.from_yaml(path)`, `GridSpec.from_mapping(value)`, `GridSpec.fingerprint`, `GridSpec.index_extent`, `GridSpec.cell_index(x, y)`, `create_grid(spec)`, `write_grid(grid, path)`, `read_grid(path)`.

- [ ] Test stable IDs/fingerprint/order, outward extent snapping, negative indices, exact and near boundaries, invalid CRS/size/bounds, and GeoParquet round-trip.
- [ ] Verify each test fails for the expected missing behavior before implementation.
- [ ] Implement decimal-stable grid extent/index arithmetic; row increases south, column east, grid IDs are `row:column`, and ordering is row/column.
- [ ] Store grid fingerprint, CRS, and spec metadata in every grid row and GeoParquet metadata; verify round-trip preserves identity and CRS.

### Task 3: Dataset inspection, CRS-aware input, and point alignment

**Files:** `src/gridforge/io/datasets.py`, `src/gridforge/align/points.py`, `src/gridforge/validation/report.py`, `tests/test_inspect.py`, `tests/test_points.py`.

**Interfaces:** `DatasetInfo`, `inspect_dataset(path, *, source_crs=None)`, `load_vector(path, *, source_crs=None)`, `align_points(points, grid, *, value_columns, aggregations, x_column='x', y_column='y', source_crs=None)`.

- [ ] Test metadata inspection for GeoJSON/GeoParquet/CSV/GeoTIFF and failure on absent/unknown CRS; test explicit CRS handling for CSV coordinates.
- [ ] Test inside/boundary/outside points, count/sum/mean/min/max, duplicate input IDs if present, empty cells, and deterministic output order.
- [ ] Run RED tests, implement only the adapters and point aggregation needed, then run the full suite.

### Task 4: Polygon alignment and coverage

**Files:** `src/gridforge/align/vector.py`, `tests/test_vectors.py`.

**Interfaces:** `align_polygons(polygons, grid, *, category_column=None, numeric_columns=(), source_crs=None)`.

- [ ] Test Polygon/MultiPolygon clipping, partial coverage, a boundary touch with zero coverage, per-category coverage, lexicographic tie-breaking, weighted means, union coverage for overlaps, and invalid geometries.
- [ ] Run RED tests and implement spatial-index candidate search plus exact intersections; use union area for unique coverage and deterministic feature-area weights for attributes.
- [ ] Verify every output contains the complete grid and coverage stays in `[0, 1]` within tolerance.

### Task 5: Raster alignment

**Files:** `src/gridforge/align/raster.py`, `tests/test_rasters.py`.

**Interfaces:** `align_raster(path, grid, *, aggregation, band=1, source_crs=None, resampling=None)`.

- [ ] Build synthetic GeoTIFF fixtures for exact grid, higher/lower resolution, different CRS, nodata, partial extent, and invalid/missing CRS.
- [ ] Test mean/min/max output, explicit resampling override, nodata preservation, and reproducible results.
- [ ] Run RED tests, warp with Rasterio to the exact canonical transform/shape, require CRS or explicit override, and record the actual resampling method.

### Task 6: Feature joins and validation reports

**Files:** `src/gridforge/join.py`, `src/gridforge/validation/dataset.py`, `src/gridforge/validation/__init__.py`, `tests/test_join.py`, `tests/test_validation.py`.

**Interfaces:** `join_features(grid, *features)`, `validate_grid(grid)`, `validate_dataset(dataset, *, grid=None)`, `ValidationReport.to_dict()`, `ValidationReport.exit_code`.

- [ ] Test duplicate/missing/extra IDs, fingerprint/CRS mismatch, duplicate feature names, inconsistent geometry, invalid geometry, outside extent, unsorted rows, invalid coverage, and null statistics.
- [ ] Implement strict identity/cardinality checks before merging, then structured PASS/WARNING/ERROR findings and JSON serialization.
- [ ] Ensure exit code is 0 without errors and 2 with errors; expected nulls and nodata appear as warnings, not fabricated zeros.

### Task 7: CLI workflows, provenance, and synthetic demo

**Files:** `src/gridforge/cli.py`, `src/gridforge/provenance.py`, `src/gridforge/demo.py`, `tests/test_cli.py`, `tests/test_provenance.py`, `tests/test_demo.py`.

**Interfaces:** CLI commands `inspect`, `grid create`, `align points|vector|raster`, `join`, `validate`, `demo`; `write_provenance(output_path, *, operation, source, grid, parameters)`.

- [ ] Add CLI tests for each core happy path, unknown CRS, grid mismatch, JSON validation, and validation exit status.
- [ ] Write sidecar provenance with GridForge version, operation, source label, CRS, grid spec/fingerprint, aggregation/resampling, output basename, and UTC creation time; do not include full lineage hashes.
- [ ] Make `demo` generate a tiny 4×4 grid plus points, polygons, and raster, run align/join/validate, and finish in seconds without external files.

### Task 8: Standalone docs and release build gate

**Files:** `README.md`, `.github/workflows/ci.yml`, project docs/examples as needed.

- [ ] Document problem, canonical grid semantics, CRS failures, point/vector/raster usage, joins, validation, Python API, GIS-library boundaries, demo, installation-name caveat, and limitations.
- [ ] Run lint, complete test suite, demo, `uv lock --check`, and `uv build`; install the wheel into a clean temporary environment and run `gridforge --help` plus demo.
- [ ] Inspect the final tree for TAG-specific code/data, untracked build artifacts, and scope leaks; report any external CI status as unverified unless a CI run is actually triggered.
