# Scripts

`REPRODUCE.md` in the repository root gives the order these run in. This file
says what each one is, so a reader can tell which scripts produced the results
and which are supporting.

## 1-setup — build the databases

| | |
|---|---|
| `generate_tpch_duckdb.py` | generate TPC-H once into `tpch10.duckdb`. **Every loader streams from this**; nothing else creates it |
| `load_pg.py`, `load_mysql.py`, `load_sqlserver.py`, `load_oracle.py` | stream that file into one vendor |
| `load_tpcc.py` | generate and load TPC-C, seeded (default 42), all four vendors |
| `oracle_groups.py` | load one Oracle working set at a time — Oracle Free caps user data at 12 GB, so SF10 fits and its indexes do not |
| `manage_indexes.py` | build and drop the indexed configuration |
| `schema_*.sql`, `create_tpcc_schema_*.sql` | DDL per vendor |
| `init_sqlserver.sh` | create the database explicitly; the mssql image ignores the init directory `docker-compose.yml` mounts (defect C12) |

`schema_oracle.sql` declares CHAR columns as VARCHAR2 on purpose. Oracle
blank-pads a comparison only when both operands are CHAR, and a bind variable is
VARCHAR2, so ORM predicates against CHAR columns match nothing while the same
predicate written as a literal matches (defect C7).

## 2-benchmark — measure

| | |
|---|---|
| `run_query.py` | **measures one cell.** Four repetitions, first discarded, median of the rest; appends immediately and takes `--resume`, so a campaign is interruptible |
| `run_tpcc.py` | the same, for a TPC-C transaction: single-client latency |
| `run_tpcc_throughput.py` | TPC-C as QPM at concurrency 50. A separate file because the 432-row grid has no column for concurrency |
| `run_<vendor>_campaign.sh` | drive a whole vendor. Each validates first and refuses to start if the system can answer a repeated query from a result cache (defect C19) |
| `mark_timeouts.py` | record a timed-out cell as `timeout` with a note, rather than leaving it absent |

Each query runs in its own process and appends its result before the next
starts, under a server-side statement timeout, so a pathological configuration
is recorded rather than stalling the campaign.

## 3-moef — plan-level analysis

Attributes a difference in time to a difference in plan: index utilisation, join
method, join enumeration, predicate handling. `run_moef_pipeline.sh` drives it.
This is where a claim about *why* a query is slower has to be settled — the
timings alone cannot distinguish a worse plan from a slower client.

## 4-analysis — derive everything reported

| | |
|---|---|
| `make_all_results.py` | **builds `results/all_results.csv`** from the raw measurements, Run after every group of measurements |
| `analyze_all.py` | the cross-system tables and the headline. Reads only `all_results.csv`, so the analysis and the results cannot disagree |
| `collect_plans.py` | `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` — PostgreSQL syntax, so PostgreSQL only |
| `collect_plans_oracle.py` | the Oracle equivalent via `DBMS_XPLAN`. Note that it *reconstructs* the ORM statement rather than intercepting it; its docstring says where that is not faithful |
| `qerror_from_plans.py` | per-operator estimated-vs-actual rows, and per-query summaries |
| `generate_figures.py`, `statistical_tests.py`, `overhead_decomposition.py`, `variance_decomposition.py`, `validate_results.py` | figures and supporting statistics |

`results/all_results.csv` is generated and never hand-edited.

## utils

`campaign_status.sh` and `count_measurements.py` report progress —
`count_measurements.py` exists because `wc -l` overcounts, as driver exceptions
embed newlines and one failed cell read as several. `assert_no_result_cache.py`
refuses to measure a system that is caching results. The rest are connection and
environment checks.


