# Measurement and analysis protocols

The frozen protocols themselves are in `campaign/rc20261008/protocols/`; every
campaign record names its protocol and the protocol's SHA-256. This page
summarises them.

## Revision campaign rc20261008

### Analytical cells (phases A, D, E, G and B)

A cell is one system, index configuration, query and framework. Each query is
timed in eight blocks. A block runs four paths on the same TPC-H input: Django
ORM, Django's handwritten SQL, SQLAlchemy ORM and SQLAlchemy's handwritten SQL.
Their order follows one of four Williams sequences, and the eight blocks are
two seeded permutations of the four, which balances position and
first-order carryover. Input set 0 is the TPC-H qualification instance and
sets 1–7 are seeded substitutions (`campaign/rc20261008/inputs-tpch.json`). A
cell warm-up on a ninth input and a warm-up of each path before each block are
recorded and never timed.

The timer is `time.perf_counter` around the query module's call, which returns
the complete list of rows. Typing, hashing, comparison and disk writes are
outside it. Every call has a 900 s ceiling, set on the server or the
connection and read back before timing. After a failure the session is
stopped and shown to be stopped before the run continues.

**Acceptance.** The full result of every timed call is compared with its
framework's handwritten baseline under result policy
`rc20261008-results-v3` (`campaign/rc20261008/code/rc_common.py`). The policy
keeps named columns, duplicate rows and the required order. Rows whose ORDER BY
keys tie may reorder. A naive midnight datetime equals its date. A float equals
an exact number only if it is that number's correctly rounded double. A decimal
is scale-equivalent only at the baseline's own declared scale, and only when
that scale has at least four fractional digits. The ORM path must also have
issued ORM-built SQL: no text literal, and not the baseline's own statement. A
block is accepted per framework; a cell enters the estimates only when all
eight blocks are accepted. Results that differ only numerically are classified
`numeric_mismatch`, timed and excluded.

**Estimand.** θ for a cell is the median over its blocks of
log(t<sub>ORM</sub> / t<sub>SQL</sub>), reported as 100·(e<sup>θ</sup> − 1).
Summaries are medians of θ. Intervals resample the queries with replacement,
2,000 times, with a seed derived from the cells; Wilcoxon tests are exact,
two-sided, on per-query medians. Paired ratios need not equal quotients of the
reported path medians.

Phase D repeats queries 6, 17, 18, 20 and 21 at scale factor 2; phase E runs
them from a separate client machine over Wi-Fi; phase G on a second server.
Cells already censored at SF1 on the host are not run there. Phase B probes
two censored cells on matched inputs and reports a lower bound on the ratio.
Cross-setting comparisons use the ratio of ratios
(1 + o<sub>new</sub>) / (1 + o<sub>reference</sub>) per matched cell.

### Transactions (phase C)

Five TPC-C-derived transactions × four systems × two index configurations × two
frameworks: 80 cells of 24 Williams-balanced blocks. Each block draws its input
from a seed fixed by the protocol, so all four paths see the same input. Before
each call the rows the input can touch are read; afterwards their committed
difference is recorded, the before-image is written back, and the restoration
is verified. A block is accepted per framework when both calls succeed, their
committed differences agree, their declared outputs agree and both reverts are
verified. Timing covers the transaction function and its commit. The estimand
is θ as above over a cell's accepted blocks.

### Four paths (phase F)

For the large-gap cells and a seeded random sample, each block times four
paths with matched inputs and indexes: the ORM call (O), the ORM's generated
SQL with its bindings executed directly (G), the handwritten SQL bound with the
ORM's values and types (B), and the handwritten SQL with literals (L). O/G is
the ORM's client-side work, G/B the formulation, B/L the binding. Plans are
captured outside timing.

### Censored-cell validation (phase V)

Each of the twelve censored framework cells was run once on its censored
input on the second server, against content-identical data, with a
239-minute ceiling in place of 900 s. Its result was compared under the same policy. Where that did not finish,
the indexed twin on the primary host supplies the evidence: it ran
byte-identical statements and parameters on the same input and data. No time
from phase V enters an estimate.

### Variability criteria

The path coefficient of variation is reported against the study's criteria:
median at most 5 %, 90th percentile at most 15 %, at most 5 % of paths above
25 %. A dataset that fails one is kept and the failure reported.

## September 2026 measurements

These are the September 2026 measurements in `results/sf1/`, the data of the
first submission, which the revised manuscript compares the campaign with.

### Analytical comparisons

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

### Transactional comparisons

Five TPC-C-derived transactions produce 80 measured cells. Latency uses
four repetitions per path, discards the first, and exports the median of the
remaining three. The six-decimal-place CSVs can produce slightly different
unrounded ratios from older higher-precision summaries. The full four-system
calculations are in `analysis/rebuild_tpcc.py`.

The 960 throughput records cover six concurrency levels (1, 4, 8, 16, 32,
50), a 10-second warmup and a 60-second measurement window. Throughput remains
separate from latency; aborts remain visible.

### Verification limits

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
