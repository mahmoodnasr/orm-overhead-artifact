# Public data dictionary

The frozen public inputs are `results/sf1/all_results.csv` and the 24 CSVs in
`results/sf1/measurements/`. Input hashes are in `PUBLIC_INPUTS.json`; the complete
release manifest is `MANIFEST.json`.

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

## Analytical columns

- `run_id`, `campaign_id`, `timestamp`, `host`: recorded execution provenance.
- `dbms`, `schema_config`, `scale_factor`, `query_id`: configuration and workload.
- `framework`, `path`: Django/SQLAlchemy and ORM/SQL.
- `block`, `sequence_id`, `position`, `param_set_id`: pairing and execution order.
- `is_warmup`: `1` is excluded; `0` identifies measured executions.
- `elapsed_s`: seconds, using successful positive finite times for ratios.
- `rows_returned`: cardinality, which is not a complete equivalence check.
- `status`, `note`, `ceiling_s`: outcome, explanation and statement ceiling.
- `load1`, `pid`, `session_id`: recorded load/process information.

## Coverage and transactional columns

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
