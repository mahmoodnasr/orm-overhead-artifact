# Data dictionary

Two datasets. The campaign's files are under `campaign/` and checksummed in
`campaign/SHA256SUMS`; the September files are under `results/sf1/`. The
release manifest is `MANIFEST.json`. Missing values are never zeros: a cell
without a value carries a status and a reason.

## Revision campaign rc20261008

System identifiers are `postgresql`, `mysql`, `oracle` and `commercial_a`;
configurations are `indexed` and `non-indexed`; frameworks `django` and
`sqlalchemy`. Times are seconds unless a column says `_ms`; overheads are
percentages, 100·(ORM/SQL − 1).

### `rc20261008/results-all-phases.csv` — one row per planned cell

| Column | Meaning |
|---|---|
| `phase`, `scale`, `dbms`, `schema`, `query`, `framework` | the cell; `query` is `Q01`–`Q22` or `T1`–`T5` |
| `status`, `status_note` | outcome and the reason in words |
| `accepted_blocks`, `acceptance` | accepted blocks and their result classes |
| `sql_s`, `orm_s`, `added_ms`, `overhead_pct` | median path times, their difference, and the paired overhead |
| `paper_overhead_pct`, `paper_sql_s`, `paper_orm_s` | the September value of the same cell, where one exists |
| `host_overhead_pct`, `mac_vs_host_ratio` | phase G: the phase A value and the ratio of ratios |
| `sf1_overhead_pct` | phases D and E: the phase A value of the same cell |
| `generated_s`, `bound_s`, `orm_vs_generated_pct`, `generated_vs_bound_pct`, `bound_vs_literal_pct` | phase F: median G and B times and the three component overheads |
| `evidence` | the records behind the row, relative to `rc20261008/` |

### Analysis outputs (`rc20261008/analysis/run-*/`)

| File | Grain | Columns or contents |
|---|---|---|
| `cells.csv` | accepted cell | `system`, `schema`, `scale`, `query`, `framework`, `theta` (log ratio), `overhead_pct`, `sql_s`, `orm_s`, `added_ms`, `classes` |
| `coverage.csv` | planned cell | `status`, `accepted_blocks`, `block_statuses`, `acceptance_classes`, `arms_not_run`, `cell_status` |
| `path_cvs.csv` | path of an accepted cell | `cv_pct` across its eight blocks |
| `censored.csv` | censored cell | the paths that exceeded the ceiling |
| `summary.json` | dataset | pooled, per-framework, per-system and per-configuration medians with intervals and counts above +100 %; Wilcoxon tests and their inclusion rule; valid cells per query; variability against the criteria |
| `sensitivity.json` | dataset | excluding each system, including numeric mismatches, excluding scale-equivalent cells, large gaps by configuration, censored worst case |
| `all-phases/summary.json` | campaign | transactions, four-path decomposition, second server, cross-setting comparisons, background-job sensitivity |
| `all-phases/F-decomposition.csv` | four-path cell | `overhead_pct`, the three components, and the dominant one |
| `all-phases/C-path-cvs.csv` | transaction path | `cv_pct` across accepted blocks |

### Records

A call record (`…/bK/aJ/{warm,timed}-<framework>-<path>.json.gz`) holds the
campaign, protocol id and hash, run id, system, configuration, scale, query or
transaction, framework, path, kind (`timed`, `block_warmup`, …), block,
attempt, Williams sequence and position, input id and parameters, ceiling,
environment, source and dataset ids, server session, process id, load before
and after, start and end time, `status`, `elapsed_s`, the statements with
their bindings, the result rows, `rows_returned` and `result_sha256`. Typed
values are stored as `{"type": …, "value": …}`. For Commercial System A the
statement text is `withheld-sha256:` and the hash of its
whitespace-normalised, lower-cased text.

A block's `decision.json` records each framework's acceptance and result class
and the comparisons behind it. Run inventories record the host, Python and
package versions, server version and settings, indexes, row counts, storage
mounts and devices, running processes and source hashes.

## September 2026 measurements

The September inputs are `results/sf1/all_results.csv` and the 24 CSVs in
`results/sf1/measurements/`. Input hashes are in `PUBLIC_INPUTS.json`.

| Files | Grain | Meaning |
|---|---|---|
| `all_results.csv` | 432 planned cells | Workload/system/index/framework identity, timings and outcome statuses |
| `<system>_<schema>.csv` | One analytical path execution | Block, parameter set, warmup, elapsed time and outcome |
| `<system>_tpcc_<schema>.csv` | One transactional path summary | Median, minimum, maximum and CV after warmup |
| `<system>_tpcc_throughput_<schema>.csv` | One path/concurrency run | Committed/aborted work, throughput and latency percentiles |

Raw files use `postgresql`, `mysql`, `oracle` or `commercial_a`; schema filename
suffixes are `indexed` and `non_indexed`. Data rows use `indexed` and `non-indexed`.
The 108 Commercial System A coverage rows retain 106 measured comparisons and
two inexpressible analytical cells. Only its name and two diagnostic notes have
been relabeled; all numerical measurements are unchanged.

### Analytical columns

- `run_id`, `campaign_id`, `timestamp`, `host`: recorded execution provenance.
- `dbms`, `schema_config`, `scale_factor`, `query_id`: configuration and workload.
- `framework`, `path`: Django/SQLAlchemy and ORM/SQL.
- `block`, `sequence_id`, `position`, `param_set_id`: pairing and execution order.
- `is_warmup`: `1` is excluded; `0` identifies measured executions.
- `elapsed_s`: seconds, using successful positive finite times for ratios.
- `rows_returned`: cardinality, which is not a complete equivalence check.
- `status`, `note`, `ceiling_s`: outcome, explanation and statement ceiling.
- `load1`, `pid`, `session_id`: recorded load/process information.

### Coverage and transactional columns

Coverage statuses distinguish `ok`, `timeout` and `not_expressible`.
Missing values are not zeros. Analytical ratios are rebuilt from paired raw blocks,
not from the coverage file's marginal times. The complete coverage export uses
the current manuscript input columns and includes every system's measurements.

Transactional latency columns include `median_s`, `min_s`, `max_s`, `cv_pct` and
`repetitions_measured` (three after warmup). Throughput columns include
`concurrency`, `duration_s`, `committed`, `aborted`, `abort_pct`, `qpm`, `qps`,
`p50_ms` and `p95_ms`. Units follow the suffixes. Throughput has no analytical
pairing/block interpretation.

Generated `cells.csv`, `systems.csv`, `cases.csv`, `summary.json`, `tpcc_cells.csv`
and `tpcc_summary.json` retain full precision. `input-sha256.json` records the
inputs consumed in the rebuild. LaTeX tables apply display rounding and carry
the Commercial System A label. Outputs are written only to `outputs/`.
