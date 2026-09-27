# GridForge v0.1 Design

## Goal

GridForge is a reusable Python library and CLI for deterministically creating a canonical spatial grid, aligning point, polygon, and raster inputs to it, joining aligned features, and validating the result. It is independent of TAG-Twin, any database, and any country-specific CRS.

## Decisions

- Python package APIs are the source of behavior; the CLI is a thin adapter over them.
- GeoPandas, Shapely, PyProj, Rasterio, PyArrow, NumPy, Pandas, PyYAML, and Typer provide file I/O, CRS operations, geometry operations, raster warping, and CLI parsing. GridForge defines the spatial and aggregation policies around those libraries.
- The distribution name is `gridforge-spatial` because PyPI's `gridforge` name is already occupied. The installed command and Python import remain `gridforge`.
- `GridSpec` requires CRS, square `cell_size`, requested `bounds`, and a top-left grid `origin`. The origin is a cell corner: column increases east, row increases south. Bounds select every cell with positive-area overlap, expanding outward to grid lines.
- Point assignment uses cells `[left, right) × (bottom, top]`. A documented metric-independent coordinate tolerance snaps near-boundary coordinates to an exact grid line before assignment. Unknown input CRS is an error unless an explicit CRS is supplied for a source without CRS metadata.
- Grid row/column indices are computed from the fixed origin, including negative values. `grid_id` is the stable `row:column` pair; `grid_fingerprint` identifies CRS, cell size, origin, and covered index extent. Dataset joins require matching fingerprints and exact grid membership.
- Aligned datasets retain every canonical cell. Counts are zero for empty point cells; other empty aggregates are null. Polygon coverage is the intersection area of the cell and the union of valid input polygons divided by cell area. Per-category area totals may overlap; category ties are resolved by ascending normalized category string. Weighted numeric polygon means use feature intersection area as weight.
- Raster alignment maps `mean`, `min`, and `max` to documented Rasterio `average`, `min`, and `max` warp resampling. This policy, source/target CRS, aggregation, band, nodata, and grid fingerprint are recorded. Unknown raster CRS and unsupported resampling are errors.
- Output is sorted by row then column. Determinism means the same logical table, geometries, IDs, and values for identical input, spec, configuration, and GridForge version; generated-at timestamps and container bytes are not part of logical equality.
- CLI builds write a small `<output>.gridforge.json` transformation record. Full source lineage, release hashes, immutable releases, orchestration, services, databases, and visualization remain outside scope.
- `gridforge validate` emits PASS/WARNING/ERROR findings as text or JSON. Exit code is 0 without errors and 2 when errors exist; warnings remain visible but do not fail CI by default.
- `gridforge demo` creates and processes a tiny synthetic 4×4 example without external or TAG-Twin data.

## Public Surface

- `GridSpec.from_yaml(path)` and `GridSpec.from_mapping(value)` parse and validate grid configuration.
- `create_grid(spec) -> geopandas.GeoDataFrame` returns `grid_id`, `grid_fingerprint`, `row`, `column`, `geometry`, and cell bounds.
- `inspect_dataset(path, *, source_crs=None) -> DatasetInfo` reports geometry/raster type, CRS, feature/band count, and bounds without guessing CRS.
- `align_points(points, grid, *, value_columns, aggregations, x_column, y_column, source_crs=None)` returns one row per grid cell and requested aggregate columns.
- `align_polygons(polygons, grid, *, category_column=None, numeric_columns=(), source_crs=None)` returns coverage, dominant category, category coverage, and weighted numeric means where requested.
- `align_raster(path, grid, *, aggregation, band=1, source_crs=None, resampling=None)` returns one raster aggregate per grid cell.
- `join_features(grid, *features)` rejects identity/schema/CRS/cardinality mismatches and returns a complete, sorted feature grid.
- `validate_grid` and `validate_dataset` return structured reports with findings and stable exit status.
- CLI commands expose inspect, grid create, align points/vector/raster, join, validate, and demo.

## Risks and Limits

- PyPI distribution-name availability can change before publication; verify immediately before any release. Publishing is outside this task.
- Raster warp behavior depends on the installed GDAL/Rasterio stack. The selected operation is recorded, and tests pin observable results for synthetic fixtures.
- Polygon feature attributes in overlaps represent per-feature contributions; unique geometric coverage uses union area. This distinction is documented in output field names and API docs.

## Acceptance

The supplied v0.1 definition of done is authoritative: a clean install can run a synthetic point/vector/raster pipeline through grid creation, alignment, join, validation, CLI, and Python API; tests, CI configuration, package build, and standalone documentation are present.
