# Revision campaign rc20261008

The measurements behind the revised manuscript. Between 8 and 11 October 2026
the full scale-factor-1 analytical grid was measured again under a new,
frozen protocol, together with the checks the reviewers asked for:
transactions under a matched design, scale factor 2, a physically separate
client, a second server, a four-path decomposition of the large gaps, and
result validation of every censored cell.

This tree is a copy of the campaign record. It was prepared for release by
copying, with the substitutions described under [What was changed for
release](#what-was-changed-for-release); nothing was recomputed by hand. The
September 2026 measurements remain in [`../results/sf1/`](../results/sf1/) as
the historical comparison.

## Verify and reproduce

From the repository root:

```sh
python review.py verify      # standard library only
python review.py reproduce   # needs requirements-analysis.txt
```

`verify` checks every file here against `SHA256SUMS`, the 728-row coverage
grid, every evidence path, and that the source each run hashed is the source
released in `source/`. `reproduce` reruns the campaign's own analysis scripts
on the released records into `outputs/campaign/` and compares the result with
the reference outputs listed below. It also re-checks every accepted
ORM/SQL pair of phases A, D and E from the full results stored in its records:
2,656, 487 and 560 pairs. No database is contacted.

## Phases

`rc20261008/results-all-phases.csv` has one row per planned cell of every
phase. A row is always present; one without a result says why in
`status_note`.

| Phase | What | Rows | Outcome |
|---|---|---:|---|
| A | SF1: 4 systems × 2 index configurations × 22 queries × 2 frameworks, on the primary host | 352 | 332 measured, 12 censored, 4 not expressible, 4 numeric mismatch |
| B | Matched-input probes of two censored cells where one path completes | 2 | 2 lower bounds |
| C | TPC-C-derived transactions: 5 types × 4 systems × 2 configurations × 2 frameworks | 80 | 64 measured, 16 measured with rejected inputs |
| D | SF2, queries 6, 17, 18, 20 and 21 | 80 | 53 measured, 14 partial, 3 censored, 10 skipped (censored at SF1) |
| E | A separate client machine over Wi-Fi, same five queries | 80 | 70 measured, 10 skipped |
| F | Four-path decomposition: ORM call, its generated SQL, handwritten SQL with the ORM's bindings, handwritten literal SQL | 42 | 41 measured, 1 censored |
| G | A second server, same five queries | 80 | 70 measured, 10 skipped |
| V | Result validation of the 12 censored cells of A | 12 | 8 validated directly, 4 by indexed twin |

Commercial System A is the anonymous fourth system; its identifier in data
and paths is `commercial_a`.

## Where the manuscript's numbers come from

| Manuscript content | File (under `rc20261008/`) |
|---|---|
| Analytical headline, per-system and per-index medians, intervals, Wilcoxon tests, query counts, variability | `analysis/run-20261011T2000/A-sf1/summary.json` |
| Sensitivity rows: excluding a system, numeric mismatches, scale-equivalent blocks, censored worst case, large gaps by index configuration | `analysis/run-20261011T2000/A-sf1/sensitivity.json` |
| Coverage of the analytical design | `analysis/run-20261011T2000/A-sf1/coverage.csv`, `results-all-phases.csv` |
| Per-cell estimates and curated cases | `analysis/run-20261011T2000/A-sf1/cells.csv` |
| SF2 and separate-client results | `analysis/run-20261011T0400/D-sf2/`, `analysis/run-20261011T2215/E-client/` |
| Transactions, second server, cross-setting comparisons, background-job sensitivity | `analysis/run-20261011T2251/all-phases/summary.json` |
| Four-path decomposition | `analysis/run-20261011T2251/all-phases/F-decomposition.csv` |
| Transaction path variability | `analysis/run-20261011T2251/all-phases/C-path-cvs.csv` |
| Censored-cell validation | `results-all-phases.csv` (phase V), `evidence/V-binding.json` |

Only these four analysis runs are released. They are the runs the manuscript
reports; earlier runs of the same scripts were working snapshots.

## Estimand

For each cell, θ is the median over its accepted blocks of
log(t<sub>ORM</sub> / t<sub>SQL</sub>), reported as 100·(e<sup>θ</sup> − 1).
Summaries take medians of θ. Intervals come from a bootstrap that resamples
the 22 queries with replacement (2,000 resamples, seed derived from the cells),
and Wilcoxon tests are exact and two-sided on per-query medians. Each framework
is compared with its own handwritten SQL baseline. The definitions are in
`rc20261008/code/rc_analyze.py` and `rc_summary.py`.

## Layout

| Path | Contents |
|---|---|
| `rc20261008/` | the campaign: records, protocols, plans, analysis, code |
| `rc20261008/<phase>/<system>-<configuration>/` | one run: `inventory-before-*.json`, `inventory-after-*.json`, `end-checks-*.json`, `run-parameters.json`, `events.jsonl`, `progress.json`, `completion.json` |
| `…/qNN/` or `…/TN/` | one query or transaction: `plan.json` (seed and block order), `cellwarm/`, `cell-done.json` |
| `…/qNN/bK/`, `…/TN/bKK/` | one block: `decision.json` (acceptance of each pair) and `aJ/` (attempt) |
| `…/bK/aJ/{warm,timed}-<framework>-<path>.json.gz` | one call: inputs, timing, session, statements, full result rows and their hash |
| `rc20261008/protocols/` | frozen protocols; every record names its protocol and hash |
| `rc20261008/plans/` | the controller's execution plans: step order of each phase |
| `rc20261008/inputs-tpch.json` | the eight matched TPC-H inputs per query, with the generator's seed and hash |
| `rc20261008/evidence/` | dataset fingerprints, plan captures, background-job overlap, censored-cell bindings, setup records |
| `rc20261008/code/` | the campaign harness and analysis, as run (see below) |
| `rc20261008/patches/` | the two transaction-baseline corrections applied before phase C |
| `oracle-clean-20261007-v2/`, `system-a-clean-20261007-v3/` | October four-path diagnostics of three large-gap cells, reused by phase F |
| `october-runner/` | the runner that produced them |
| `plan-diagnostics-20260919/` | the September execution-plan diagnostics of selected outliers |
| `source/measured/` | the 109 source files every analytical run hashed, byte for byte |
| `source/tpcc-run/` | the transaction run's files that differ from, or are absent from, `measured/` |
| `SHA256SUMS`, `release-provenance.json`, `WITHHELD.json` | integrity and release records |

Records are JSON. Floats, decimals and dates are stored as
`{"type": …, "value": …}` so that a value reads back exactly;
`rc20261008/code/rc_common.py` (`load`, `untyped`) decodes them.

## Bindings

Every record carries its campaign, protocol id and hash, run id, environment
id, dataset id, input id and server session. `source_sha256` is the digest
of the source-hash map in the run's inventory: `4137b2a6…` for every analytical
run, recomputable from `source/measured/`. The inventories record the host,
software and server versions, settings, indexes, row counts, storage mounts,
block devices and the processes running before and after each run. The
environment id is a digest over the unredacted inventory; for that reason it
can be compared between records but not recomputed from the released copy.

## Which run counts

| Case | Used | Kept, superseded |
|---|---|---|
| Separate client, Commercial System A without secondary indexes | `E-client/commercial_a-non-indexed-r2` | `E-client/commercial_a-non-indexed`: it followed a long indexed workload on the same engine instance without a restart. The engine's retained memory shrank its data cache, and the baseline scans read from disk. Rerun on a freshly started engine, as in phase A. |
| Transactions, Oracle without secondary indexes | `C-tpcc/oracle-non-indexed-r2` | `C-tpcc/oracle-non-indexed`: it overlapped a backup snapshot |
| Four-path cells | newest protocol present: `F-fourpath/v3`, then `v2`, then the first protocol | earlier protocols' cells, listed in each row's note |
| Second server | `G-mac-server/v2/` (protocol G-v2) | the protocol G-v1 directories directly under `G-mac-server/` |
| Censored-cell validation | `V-censored/v2/` | `V-censored/postgresql-non-indexed`: protocol V-v1, stopped before execution because the engine reported the extended ceiling in a form the frozen read-back rejected |
| Phase D, Django Q21 | excluded as `partial` | the blocks before the first rejected input |

`pilot*/` hold the pilots that fixed the protocols, `HALTED*` files mark runs
a gate stopped, and `*-cancel-*` directories are cancellation tests. None of
them enters an estimate.

## Known limitations and open differences

These are reported as measured; none was resolved by re-measuring until the
answer changed.

- **Transaction variability** exceeds the analytical criteria: median path CV
  5.7 %, 90th percentile 25.5 %, 12.5 % of paths above 25 %. Each block uses a
  different seeded input, so these CVs include input-to-input variation; the
  paired ratio controls for it.
- **Order-Status rejections.** 52 of 1,920 transaction blocks were rejected,
  all Order-Status: for a customer with no order, the ORM implementations
  return fewer fields than the SQL baselines. The ORM code was not changed.
- **Django Q21** counts distinct orders per supplier where TPC-H counts
  lineitems. Its results were exact at SF1 on all eight inputs; at SF2 one
  input differs, so those cells are `partial`. The Q21 overheads time this
  formulation.
- **Commercial System A, indexed Q18 with Django.** Its ORM path took
  249–318 s in the October diagnostic and 358–370 s in all eight phase A
  blocks, on the same server build. The cause is not identified. The cell is
  above +6,000 % in every run.
- **Separate client, Commercial System A without indexes, Django Q21:** 0.74
  of phase A's ratio after the rerun.
- **Commercial System A's server** was updated to a newer build after the
  September measurements and before this campaign. 16 of the 19 phase A cells
  that moved by more than 10 % against September are on that system. The update
  is a candidate cause, not an established one.
- **Transaction inventories** did not read the server version. The host's
  package history shows no database server, driver or runtime change during
  the campaign; that log is not part of this release.
- **Oracle's per-process CPU cross-check** did not run: its process-name pattern
  did not match the process's lower-case name. The CPU and memory limits of
  Oracle's control group were verified on every Oracle run.
- **Host timers** stayed enabled. `evidence/background-jobs/` records every
  overlap. Without the overlapping blocks, the pooled medians are unchanged to
  three decimals.

## What was changed for release

`release-provenance.json` lists every file that differs from the campaign
record, with the SHA-256 of the original and of the released copy. Every other
file is a byte-identical copy.

- **Commercial System A** is relabelled `commercial_a` in data, paths and
  text, as the licence of its software requires for benchmark results. In its
  records, the SQL text, execution plans, server version, configuration and
  catalogue values, and the driver's error messages are replaced by SHA-256
  placeholders. The record keeps its structure and every timing, input, row
  count and full result. A statement's placeholder is the hash of its
  whitespace-normalised, lower-cased text, so the check that an ORM path did
  not issue its baseline's statement still runs on the released records.
  Execution-plan files of this system are withheld; `WITHHELD.json` lists each
  with its original hash. Data never names the product. The one exception is
  the file names that source-hash maps and checksum lists must carry, because
  the adapter code is released and those names identify its files. Two harness
  scripts whose names carried the product name are released as
  `rc_commercial_a_probe.py` and `rc_e_rerun_commercial_a_ni.sh`.
- **Private host details** are replaced: home directories, host and user names,
  network addresses, disk serial numbers, an unrelated service that shared the
  host, and desktop applications on the client.
- **Not released**: the controller's state and logs, the host/client
  synchronisation and backup tools, a privileged host-administration helper,
  and internal working notes. None holds a measurement.
- **Code.** `rc20261008/code/` holds the harness as run, with the host details
  above replaced. The offline analysis scripts (`rc_common.py`, `rc_analyze.py`,
  `rc_collect.py`, `rc_summary.py`, `rc_all_results.py`) additionally read and
  write `commercial_a`, take their historical comparison from
  `analysis/reference/derived/`, and write to `$RC_OUT` when it is set. In the
  other scripts, host paths inside strings were replaced and the fourth system
  was relabelled only in comments and docstrings; no other token changed. The
  hashes that protocols pin for these scripts therefore refer to the unreleased
  originals. `source/` is byte for byte.

## Running new measurements

The harness expects the campaign host: a privileged helper that sets the CPU
governor and confines each database service, systemd control groups, and
databases loaded as described in [`../REPRODUCE.md`](../REPRODUCE.md). It is
released so that the protocol can be read and audited, not as a turnkey
runner. A new run on other hardware is a new experiment; give it its own
protocol and output directory.
