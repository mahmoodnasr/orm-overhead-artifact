# Measurement and analysis protocol

The current manuscript uses scale factor 1. The retained inputs comprise
PostgreSQL, MySQL, Oracle and Commercial System A, with all measurement values
and results included.

## Analytical comparisons

The analytical design contains four systems, two index configurations, two
frameworks and 22 query templates: 352 planned cells. There are 336 finite
measured cells (165 Django, 171 SQLAlchemy), 12 censored cells and four
inexpressible cells. All systems remain included in the coverage grid and analysis.

Each measured cell has eight paired ORM/SQL blocks. All four framework/access
paths share the block's parameter set. Williams sequences balance execution
position and first-order carryover. Warmup records are retained and excluded
from the estimates.

For each block, compute `log(ORM elapsed / SQL elapsed)`. A cell estimate is the
median of its eight block log ratios, transformed to percentage overhead as
`100 * expm1(estimate)`. Aggregate summaries take medians on that log scale
before back-transformation. Paired ratios need not equal quotients of separately
reported marginal path medians.

The bootstrap resamples the 22 query templates with replacement and retains
their available configurations together. The code uses 2,000 draws and a
deterministic seed derived from the selected cells, matching the manuscript's
estimator. The analysis reproduces the full four-system headline and all
sensitivity rows, including the three-system subset.

## Transactional comparisons

Five TPC-C-derived transactions produce 80 measured cells. Latency uses
four repetitions per path, discards the first, and exports the median of the
remaining three. The six-decimal-place CSVs can produce slightly different
unrounded ratios from older higher-precision summaries. The full four-system
calculations are in `analysis/rebuild_tpcc.py`.

The 960 throughput records cover six concurrency levels (1, 4, 8, 16, 32,
50), a 10-second warmup and a 60-second measurement window. Throughput remains
separate from latency; aborts remain visible.

## Verification limits

Integrity checks establish that the full grid includes every system's measurements,
paired cells have the expected block structure, runtimes are positive,
and files match their checksums. Reproduction compares generated CSV, JSON and
LaTeX with the public references and regenerates the three PDF figures. Numeric
comparisons allow absolute and relative tolerance of `1e-12` for platform math
libraries; table text and input checksums must match exactly.

These checks do not execute a database or prove historical whole-result
equivalence. Individual historical rows lack source hashes and server versions.
The validator has limitations involving named columns, duplicate rows, required
ordering and numeric tolerance. Transactional equivalence also requires checking
database-state changes. A repaired query must be validated and remeasured; source
edits alone cannot repair its old timings.

Each ORM is compared with its own handwritten baseline. Django uses a cursor;
SQLAlchemy uses Session execution with a text statement. These layers differ,
so the percentages do not establish a framework ranking. The differing analytical
and transactional protocols also limit cross-workload conclusions.
