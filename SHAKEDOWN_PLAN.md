# Shakedown plan — prove the harness on tiny data, then measure once

Written 2026-09-04, after four defects were found *inside* SF1 campaigns rather
than before them, each costing a full run:

| # | Defect | Cost |
|---|---|---|
| 1 | SQL Server measured while `auto_create_stats` was still building statistics | 1 campaign |
| 2 | Query Store on, flushing to disk mid-measurement | 1 campaign |
| 3 | Per-block warmup warmed one rotating path, biasing it asymmetrically | all campaigns |
| 4 | `Q13NotExpressible` recorded as `error`, scoring a campaign NO-GO | 1 campaign |

Every one of them was reachable at scale factor 0.01 in under a minute. None of
them was reachable by the checks that were being run, which asked whether the
plumbing worked and never whether the measurement was sound.

**The rule this plan exists to enforce: no campaign at SF1 until the identical
campaign has run end to end at SF0.01 on all four engines and passed the gate.**

---

## Two optimisations that shape the order

**Non-indexed first, always.** A freshly loaded TPC-H schema has primary keys
and no secondary indexes — it *is* the non-indexed configuration. Measuring it
first costs zero setup; measuring indexed first means creating 15 indexes, then
dropping them again. Same for TPC-C's nine. Every load in this plan is followed
immediately by its non-indexed campaign, then one `--action create`, then the
indexed campaign. No drop is ever needed.

**One engine live at a time.** `bench-host apply <engine>` stops the other
three. The shakedown databases are separate (`tpch_tiny`, `tpcc_tiny`) so the
SF1 data on each server is untouched and does not have to be reloaded.

---

## Phase 0 — freeze the harness  (~20 min, no measurement)

Nothing in `scripts/` changes after this phase until Phase 3 completes. A fix
applied mid-campaign is what produced the table above.

0.1 Commit the already-made fixes: all-four-path block warmup in
    `run_block.py`, `not_expressible` status, `--action analyze`,
    `preflight.py`, the `sqlserver` alias in `bench-host`.

0.2 `python3 -m pytest tests/ -q` — the existing guards must pass, in
    particular `test_paramsets.py` and `test_parameters_take_effect.py`.

0.3 Tag it: `git tag harness-frozen-sf1` so any later drift is visible as a
    diff rather than as a surprise.

---

## Phase 1 — shakedown at SF0.01  (~2 h total, all four engines)

Scale factor 0.01 is the smallest DuckDB's dbgen emits with every table
non-empty: **lineitem 60,175 rows, orders 15,000, customer 1,500, part 2,000,
partsupp 8,000, supplier 100, nation 25, region 5**. Roughly 12 MB. Every
TPC-H query returns rows, so `ROWS>0` still means something, and a full
22-query eight-block campaign takes minutes rather than hours.

TPC-C shrinks the same way: **1 warehouse, 10 districts, 300 customers per
district**, via `TPCC_WAREHOUSES=1 TPCC_ORDERS=30 TPCC_HISTORY=10`. About
40,000 rows. Enough for all five transactions to touch every table.

### 1.1 Generate once (~1 min)

```bash
cd ~/MCs/code/orm-benchmark-reproducibility && source venv/bin/activate
export PYTHONPATH=. TPCH_SF=0.01
python3 scripts/1-setup/generate_tpch_duckdb.py --scale 0.01 --out /tmp/tpch_tiny
```

### 1.2 Per engine, in this order: PostgreSQL, MySQL, SQL Server, Oracle

The order is by how much is already known to work, so a failure in the first
engine is cheapest to diagnose.

For each `E` in that list:

```bash
sudo bench-host apply $E && sudo bench-host verify $E     # must exit 0
source scripts/0-host/campaign-env.sh $E
export TPCH_SF=0.01 TPCH_DB=tpch_tiny TPCC_DB=tpcc_tiny

# a. create the two tiny databases (one privileged step per engine)
# b. apply schema_<E>.sql and create_tpcc_schema_<E>.sql
# c. load TPC-H (12 MB) and TPC-C (1 warehouse)
python3 scripts/1-setup/manage_indexes.py --database $ALIAS --action analyze

# d. NON-INDEXED first - nothing to drop, the load left it that way
python3 scripts/0-host/preflight.py --dbms $E --schema non-indexed
bash scripts/2-benchmark/run_pilot.sh $E non-indexed campaign
python3 scripts/4-analysis/pilot_gate.py results/shakedown/${E}_non_indexed.csv
bash scripts/2-benchmark/run_tpcc_campaign.sh $E non-indexed
python3 scripts/2-benchmark/run_tpcc_throughput.py --dbms $E --schema non-indexed \
    --concurrency 4 --duration 10 --out results/shakedown/${E}_tput_non_indexed.csv

# e. then INDEXED - one create, no drop
python3 scripts/1-setup/manage_indexes.py --database $ALIAS --action create
python3 scripts/1-setup/manage_indexes.py --database $ALIAS --benchmark tpcc --action create
python3 scripts/0-host/preflight.py --dbms $E --schema indexed
bash scripts/2-benchmark/run_pilot.sh $E indexed campaign
python3 scripts/4-analysis/pilot_gate.py results/shakedown/${E}_indexed.csv
bash scripts/2-benchmark/run_tpcc_campaign.sh $E indexed
python3 scripts/2-benchmark/run_tpcc_throughput.py --dbms $E --schema indexed \
    --concurrency 4 --duration 10 --out results/shakedown/${E}_tput_indexed.csv
```

### 1.3 What the shakedown must demonstrate

Not speed — the numbers are meaningless at this size. **Coverage.** The pass
condition is that every one of these is true on all four engines:

- [ ] `preflight.py` exits 0 in both configurations
- [ ] all 22 TPC-H queries execute on all four paths, or fail with a *declared*
      status (`timeout`, `not_expressible`) and no other
- [ ] `pilot_gate.py` design-integrity section passes: 8 blocks × (4 − censored)
      paths, every path in every position, 8 distinct parameter sets, each
      Williams sequence twice
- [ ] §8.2 completeness passes — zero undeclared failures
- [ ] the drop/create cycle reaches 15/15 and 0/15 for TPC-H, 9/9 and 0/9 for
      TPC-C, with zero failures, on every engine
- [ ] all five TPC-C transactions commit on all four paths, zero aborts
- [ ] the throughput harness completes at one concurrency level
- [ ] `make_all_results.py --scale 0.01` builds without a blank cell

§8.1 noise and §8.3 ceiling are **not** pass conditions here: at 12 MB
everything is sub-millisecond and CV is dominated by timer granularity. They
are checked at SF1 only.

---

## Phase 2 — fix, then re-shake  (as long as it takes)

Every defect Phase 1 finds is fixed, written into `docs/CORRECTIONS.md`, and
then **Phase 1 is run again from the start on all four engines**. Not just the
engine that failed — three of the four defects above were vendor-specific in
where they surfaced and general in where they applied.

Phase 3 does not begin until Phase 1 passes clean on a single unmodified
harness.

---

## Phase 3 — the SF1 measurement campaigns

Only now. Same commands, `TPCH_SF=1`, the real `tpch`/`tpcc` databases, and
`results/sf1/measurements/`.

Current state of each server, which decides the work:

| Engine | TPC-H data | Index state now | TPC-C data |
|---|---|---|---|
| PostgreSQL | loaded | **non-indexed** | loaded |
| MySQL | loaded | **non-indexed** | loaded |
| SQL Server | loaded | indexed | schema only |
| Oracle | loaded | unknown | none |

So PostgreSQL and MySQL are already in the cheap starting state.

**Order, one engine at a time, non-indexed before indexed:**

1. **PostgreSQL** — non-indexed TPC-H + TPC-C, then `--action create`, indexed
   TPC-H + TPC-C. (~7 h)
2. **MySQL** — same. (~15 h; its non-indexed TPC-H is the single longest run)
3. **SQL Server** — drop indexes once to reach the cheap state, then as above.
   Load TPC-C first. (~6 h)
4. **Oracle** — load TPC-C, then as above. Q09/Q20 may not fit; censoring
   handles it. (~8 h)

Every campaign is preceded by `preflight.py` and followed by `pilot_gate.py`,
and no result is kept unless the gate exits 0.

All previous SF1 measurements are superseded by the warmup change and move to
`results/sf1/superseded/` with the reason in the filename.

---

## Phase 4 — analysis

`make_all_results.py --scale 1`, then the figures. Unchanged from
`SF1_RERUN_PLAN.md`.

---

## Why this is faster than continuing as we were

The four defects cost roughly four full campaigns — call it 20 hours of machine
time and several days of elapsed time, because each was found near the *end* of
a run. Phase 1 exercises the identical code path on 12 MB instead of 1 GB. A
defect that takes eight hours to reach at SF1 takes four minutes to reach at
SF0.01, and the fifth defect — whatever it is — is found before the clock
starts rather than after it has run out.
