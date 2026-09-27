# GridForge

[![CI](https://github.com/KageRyo/GridForge/actions/workflows/ci.yml/badge.svg)](https://github.com/KageRyo/GridForge/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/gridforge-spatial)](https://pypi.org/project/gridforge-spatial/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

GridForge is a Python toolkit and CLI for building canonical spatial grids and aligning point, polygon, and raster data to them. It produces complete, deterministic grid feature datasets that can be joined, validated, and traced back to the spatial transformation settings.

Ordinary spatial joins answer questions such as which features intersect a geometry. They do not by themselves define stable cell IDs, edge behavior, coverage calculations, raster resampling, missing-cell policy, or whether two outputs use the same grid. GridForge makes those choices explicit.

GridForge was extracted from spatial data engineering patterns developed for real-world digital-twin and environmental data pipelines. It is independent of those systems and does not depend on their schemas or private data.

## Install

The PyPI distribution is named `gridforge-spatial` because `gridforge` is already used by an unrelated package. The Python import and executable remain `gridforge`.

```bash
python -m pip install gridforge-spatial
gridforge --help
```

For development, install the project and its tools with [uv](https://docs.astral.sh/uv/):

```bash
uv sync --all-groups
uv run gridforge --help
```

## Quick start

Run the bundled synthetic workflow to build a 4 × 4 grid, align points, polygons, and a raster, join their features, and validate the result:

```bash
gridforge demo --output-dir ./gridforge-demo
```

The demo writes only synthetic files under the requested directory. It completes locally without downloads or project-specific inputs. Expected uncovered cells and point nodata are reported as warnings; validation exits with status `0` unless it finds an error.

## Canonical grids

A canonical grid is a fixed-origin set of square cells with one projected CRS, one cell size, stable row and column indices, and a stable identity. Create a YAML specification:

```yaml
crs: EPSG:3857
cell_size: 20
bounds:
  min_x: 0
  min_y: 0
  max_x: 80
  max_y: 80
origin:
  x: 0
  y: 80
```

The origin is the top-left cell corner; columns increase east and rows increase south. Bounds include cells with positive-area overlap and expand outward to cell boundaries. Coordinates and cell size use the units of the projected CRS. Geographic CRSs are rejected for canonical grids.

Cell IDs are stable `row:column` pairs, including negative indices when the grid extends west or south of its origin. Grid rows are ordered by row and then column. Grid fingerprints identify the normalized CRS, cell size, origin, and covered index extent, so different requested bounds that resolve to the same cells have the same logical grid identity.

Point assignment uses cells `[left, right) × (bottom, top]`: a point on a shared vertical edge belongs to the cell to its east, and a point on a shared horizontal edge belongs to the cell to its south. Coordinates within the configured `boundary_tolerance` (default `1e-9` CRS units) of a grid line snap to that line before assignment.

Build and save the grid as GeoParquet:

```bash
gridforge grid create grid.yaml --output grid.parquet
```

GridForge writes the cell geometry, row and column, grid ID, fingerprint, CRS, and specification. It also writes a `grid.parquet.gridforge.json` spatial provenance sidecar.

## Inspect inputs and CRS rules

`inspect` reads vector files, GeoParquet, CSV or Parquet coordinate tables, and raster files without guessing a CRS:

```bash
gridforge inspect stations.csv --source-crs EPSG:3826 --json
gridforge inspect landuse.geojson
gridforge inspect dem.tif
```

CSV and ordinary Parquet tables need explicit `--source-crs`; use `--x-column` and `--y-column` if their coordinate fields are not named `x` and `y`. Vector and raster files use embedded CRS metadata when available. If a file has no CRS, pass `--source-crs`; if an explicit CRS conflicts with embedded metadata, GridForge returns an error. It never silently assumes WGS84.

## Align points

For each point, GridForge reprojects into the grid CRS, assigns the point to a containing cell, and aggregates requested columns. Supported operations are `count`, `sum`, `mean`, `min`, and `max`:

```bash
gridforge align points stations.csv \
  --grid grid.parquet \
  --source-crs EPSG:3826 \
  --value rainfall_mm \
  --agg mean \
  --output rainfall.parquet
```

The output keeps every grid cell. `point_count` is zero in empty cells; empty numeric aggregates remain null. A `count` aggregation counts non-null values in the selected column.

## Align polygons

Polygon and MultiPolygon features are reprojected to the grid CRS and intersected with cells. The output includes `polygon_count` and `polygon_coverage_ratio`; coverage is the union of intersected area divided by cell area, so overlapping polygons cannot inflate total coverage above one. Category coverage is calculated as a separate union for each category, so ratios across different categories may sum above one when categories overlap. Dominant category ties are resolved by normalized category name in lexical order. Numeric attributes use an intersection-area weighted mean over features with non-null values.

```bash
gridforge align vector landuse.geojson \
  --grid grid.parquet \
  --category landuse \
  --numeric-column impervious_fraction \
  --output landuse.parquet
```

Use repeated `--numeric-column` options for multiple numeric fields. To produce coverage only, omit `--category` and `--numeric-column`.

## Align rasters

Raster alignment first warps the selected band into the grid CRS, then aggregates valid pixels in each canonical cell using `mean`, `min`, or `max`. Reprojection resampling defaults to `nearest`; choose `bilinear` or `cubic` explicitly when appropriate. Nodata and cells outside the raster footprint remain null.

```bash
gridforge align raster dem.tif \
  --grid grid.parquet \
  --agg mean \
  --resampling bilinear \
  --output elevation.parquet
```

The aggregation maps to Rasterio's `average`, `min`, or `max` resampler. Reprojection resampling and cell aggregation are distinct operations and both are recorded in the output metadata and provenance sidecar.

## Join and validate

Join one or more GridForge-aligned GeoParquet datasets after checking grid fingerprint, CRS, cell geometry, complete cell coverage, and duplicate feature names:

```bash
gridforge join grid.parquet rainfall.parquet landuse.parquet elevation.parquet \
  --output features.parquet
```

Validate an output against its canonical grid. JSON output is suitable for CI scripts:

```bash
gridforge validate features.parquet --grid grid.parquet --json
```

Validation reports `PASS`, `WARNING`, or `ERROR`. Null or nodata feature values are warnings; structural problems, invalid geometry, mismatched grid identity, impossible coverage ratios, and infinite numeric values are errors. The command exits `0` for PASS or WARNING and `2` for ERROR, making it usable as a CI gate.

## Python API

The same operations are available without invoking the CLI:

```python
from gridforge.align.points import align_points
from gridforge.align.raster import align_raster
from gridforge.align.vector import align_polygons
from gridforge.grid import GridSpec, create_grid
from gridforge.io.datasets import load_points, load_vector, read_dataset, write_dataset
from gridforge.io.grid import read_grid, write_grid
from gridforge.join import join_features
from gridforge.validation import validate_dataset

spec = GridSpec.from_yaml("grid.yaml")
grid = create_grid(spec)
write_grid(grid, "grid.parquet")

points = load_points("stations.csv", source_crs="EPSG:3826")
polygons = load_vector("landuse.geojson")
rain = align_points(points, grid, aggregations={"rainfall_mm": "mean"})
land = align_polygons(polygons, grid, category_column="landuse")
dem = align_raster("dem.tif", grid, aggregation="mean", resampling="bilinear")

features = join_features(grid, rain, land, dem)
report = validate_dataset(features, grid=grid)
write_dataset(features, "features.parquet")
assert report.exit_code == 0, report.to_dict()
reloaded = read_dataset("features.parquet")
```

`GridSpec.from_mapping(...)` is also available when the specification comes from a Python dictionary. Input loaders and aligners accept `source_crs` only when needed; an embedded CRS is checked rather than overwritten.

## GIS libraries and boundaries

GridForge uses [GeoPandas](https://geopandas.org/) and [PyArrow](https://arrow.apache.org/docs/python/) for vector and GeoParquet I/O, [Shapely](https://shapely.readthedocs.io/) for geometry operations, [PyProj](https://pyproj4.github.io/pyproj/stable/) for CRS interpretation and transformation, [Rasterio](https://rasterio.readthedocs.io/) for raster warping and nodata handling, and [NumPy](https://numpy.org/) and [Pandas](https://pandas.pydata.org/) for data operations. Those libraries provide the underlying GIS primitives; GridForge defines canonical grid identity, boundary rules, aggregation behavior, validation, and transformation metadata.

For Taiwan-specific coordinate and address convenience functions, see [TaiGeotrans](https://github.com/KageRyo/TaiGeotrans). GridForge can consume data prepared with it, but does not depend on it or include country-specific CRS helpers in its core.

GridForge does not provide map rendering, a server, an ETL scheduler, a machine-learning framework, or country-specific CRS transformation helpers. Its provenance sidecars capture spatial transformation settings and output identity; full dataset lineage and artifact release integrity belong in dedicated tools.

## License

GridForge is licensed under Apache-2.0. See [LICENSE](LICENSE).
