# Limitations

Written to be lifted into the paper and the thesis. Each entry states the
limitation, the evidence for it, and what it does and does not invalidate.

The distinction that runs through all of them: this study's claim is **ORM
against hand-written SQL within one system**, where both arms run in the same
process, against the same server, under the same settings, in the same campaign.
Almost nothing below touches that. What they constrain is comparison *across*
systems.

---

## 1. Oracle runs on a fifth of the CPU and a third of the memory

**The limitation.** Oracle Database Free is licence-limited to **2 CPU threads,
2 GB RAM and 12 GB of user data**. The other three systems were each given 10
CPUs and a 3-4 GB data cache with no data limit.

**The evidence.** The caps are enforced by the software, not chosen by us.
Raising them was attempted and refused:

    ALTER SYSTEM SET cpu_count = 10            ORA-02097: specified value is invalid
    ALTER SYSTEM SET sga_max_size = 4G         ORA-65040: not allowed from within a PDB
    ALTER SYSTEM SET parallel_max_servers = 8  accepted, still reads 1 (derived from cpu_count)

So Oracle executes every query on one thread with a 1.5 GB SGA, while PostgreSQL
and SQL Server each use eight parallel workers against 3-4 GB.

**What it invalidates.** Oracle's absolute execution times cannot be compared
with the other three systems', and neither can its overhead *percentages* be
placed beside theirs without this caveat: overhead is a ratio, and a slower
database half makes the ORM's fixed per-row cost a smaller share of the total.

**What it does not invalidate.** Every ORM-versus-SQL comparison within Oracle.
Both access paths run under the same 2 CPUs, so the ratio in any single Oracle
row is as sound as any other system's.

**Why it was not fixed by paying.** A licensed Standard or Enterprise Edition
lifts the caps, and Oracle's commercial agreements carry the same
benchmark-disclosure clause as the developer licence — the customer may not
disclose the results of any benchmark test without Oracle's prior consent. A
thesis and a conference paper are exactly that disclosure. The Free Use Terms
covering the image actually used carry no such clause, which is why this study
runs on it. **The cap is a licensing constraint before it is a technical one.**

## 2. Oracle's grid has holes, and the indexed row has most of them

**The limitation.** The 12 GB data cap means TPC-H SF10 (10.81 GB loaded) fits
but its indexes do not.

| | Cells measured |
|---|---|
| PostgreSQL, MySQL, SQL Server | 176 / 176 each |
| Oracle non-indexed | 40 / 44 |
| **Oracle indexed** | **10 / 44** |

Queries are measured per *working set*: only the tables a query group references
are held resident (`scripts/1-setup/oracle_groups.py`). Q09 and Q20 need
LINEITEM, ORDERS, CUSTOMER, PART and PARTSUPP together, which reaches 12.37 GB
and raises **ORA-12954** on the PARTSUPP primary key. The indexed configuration
is reachable only for the five queries that never read LINEITEM.

**What it means for the paper.** Oracle's indexed row rests on five queries, not
twenty-two. Any statement about indexing on Oracle must say so, and Oracle should
not be included in aggregate indexed-versus-non-indexed statistics without it.

## 3. SQL Server runs under x86-64 emulation

There is no arm64 build of `mcr.microsoft.com/mssql/server`, and the host is
Apple Silicon. SQL Server is therefore emulated, and its absolute times carry a
penalty the other three do not. Its ORM-versus-SQL ratios are unaffected: both
arms run in the same emulated process.

## 4. Per-query CPU cannot be equalised, because MySQL cannot be raised

Resource *allocation* is identical — same CPU count, same memory ceiling, same
disk, declared in `docker-compose.yml`. Per-query *utilisation* is not, and
cannot be:

| System | Threads per TPC-H query |
|---|---|
| PostgreSQL | 8 (+leader) |
| SQL Server | 8 |
| Oracle | 1 (licence cap) |
| **MySQL** | **1 — no setting can change it** |

MySQL 8.0 has no intra-query parallelism. Measured with
`innodb_parallel_read_threads = 8` as the only variable: `SELECT COUNT(*)` went
from 0.40 s to 0.09 s, while a `GROUP BY` with aggregation and a sort went from
1.64 s to 1.69 s — no effect. The setting reaches bare clustered-index scans and
nothing else. See `docs/PARALLELISM.md`.

Parallelism was therefore set to 8 where the engine supports it rather than
lowered to 1 everywhere, since serialising the other three would measure a
configuration nobody deploys.

## 5. One campaign has no surviving log

Every measurement in this study was taken on the one Apple M4 described above.
MySQL's non-indexed campaign has no surviving log, so the server build it ran
against was never recorded; the column says so rather than asserting the other
campaign's version.

This entry previously claimed two machines, on the strength of that missing log
alone. See C30.

## 6. TPC-C is 10 warehouses, and fits entirely in cache

926 MB across 4,889,141 rows. The whole database fits in every system's data
cache, so TPC-C here measures in-memory transaction cost with essentially no
I/O. That is arguably the right condition for isolating ORM overhead, and it is
not a throughput result for a disk-bound system.

TPC-C is also reported two ways — single-client latency (in the 432-row grid)
and throughput at 50 concurrent clients (in a separate file, since the grid has
no column for concurrency). The two are not interchangeable.

## 7. Three queries cannot be expressed or completed everywhere

- **Q13 through Django's ORM** is inexpressible on SQL Server *and* Oracle.
  Django has no derived-table construct, and both systems forbid a subquery in a
  `GROUP BY` expression (`ORA-22818`; mssql-django's
  `supports_subqueries_in_group_by = False`). SQLAlchemy expresses it via
  `.subquery()`. Recorded as C17.
- **Q17 through Django's ORM** exceeds the 900 s ceiling on Oracle.
- **Q09 and Q20** are unmeasurable on Oracle at all (limitation 2).

These are results, not gaps: a query one ORM can state and the other cannot is a
difference in expressive power.

## 8. Scale is SF10 and 10 warehouses, not what the paper currently claims

`New_Paper_For_SPE/main.tex` states 100 GB TPC-H and 100-warehouse TPC-C, and
describes TPC-C transactions run "via both ORMs and SQL stored procedures". The
repository contains SF10, a generator that sets `NUM_WAREHOUSES = 10`, and no
stored procedures in any dialect. The text must be corrected to what was
measured.

## 9. The QPM metric hands SQLAlchemy a small handicap the latency metric does not

`scripts/2-benchmark/run_tpcc_throughput.py` builds its SQLAlchemy engine with
`pool_pre_ping=True`. That issues a liveness check on every checkout from the
pool, and because a `Session` releases its connection at each commit, the check
fires once per transaction. Django's path in the same script does not do it.

Measured directly on an idle PostgreSQL, median of 400 checkouts:

| | median |
|---|---:|
| checkout + `SELECT 1`, `pool_pre_ping=False` | 0.1951 ms |
| checkout + `SELECT 1`, `pool_pre_ping=True` | 0.2494 ms |
| **cost of the pre-ping** | **0.0543 ms per transaction** |

Against the shortest SQLAlchemy transaction in the whole throughput set —
PostgreSQL non-indexed T2 on the SQL path, p50 5.540 ms at concurrency 50 —
that is **0.98 %**, and it is smaller everywhere else. So the QPM figures
understate SQLAlchemy by up to one percent relative to Django, and the numbers
are reported as measured rather than re-run for it.

Two things bound the damage. **The 432-row grid is unaffected**: `run_tpcc.py`
and `run_query.py` build plain engines with no pre-ping, so every overhead
figure in `all_results.csv` — including the headline TPC-C medians — is free of
it. And the effect is an order of magnitude below the difference it could
disturb: SQLAlchemy's TPC-C overhead is +68.1 % against Django's +115.7 %.

It is recorded because it is the same shape as C20 — a configuration difference
between the two frameworks' harness code, not between the frameworks — and that
class of defect has already reached this results file twice. The difference here
is that it was quantified before it was dismissed.

One row in 120 also carries a `QueuePool limit ... timed out` note, on the
fastest path measured (125,747 QPM), where 70 transactions in 125,945 aborted:
0.06 %. Aborted transactions are counted and reported separately rather than
dropped, so they depress the QPM figure honestly instead of silently improving
it.

## 10. Oracle's indexed configuration is a per-query index subset, and reaches only one more query

`scripts/1-setup/oracle_query_indexes.py` builds, for one query, only the
indexes whose **leading column appears in that query's SQL**. An index whose
leading column is absent cannot be used for a range scan, cannot supply ordering
for a sort or merge join, and cannot drive a nested-loop join, so for the query
being measured the subset is plan-equivalent to the full set.

**The state of the database around it is not equivalent.** The other three
systems hold every index of the configuration simultaneously. Oracle holds one
query's subset at a time, so a comparison *between* Oracle's indexed queries
inherits that difference; a comparison between the ORM and SQL arms of a single
cell does not, because both arms see the same subset.

It recovered **2 cells of the 34**, and the reason it recovered so few is worth
stating precisely, because it is the sharpest measurement of the licence limit
in this study:

| | measured |
|---|---:|
| LINEITEM data | 7.18 GB |
| LINEITEM primary key | 1.25 GB |
| **left for indexes, of the 12 GB cap** | **~3.5 GB** |
| `idx_lineitem_partkey` | 1.06 GB |
| `idx_lineitem_shipdate` | 1.25 GB |
| `idx_lineitem_shipdate_discount_qty` | does not fit beside the above |
| `idx_lineitem_shipmode_receiptdate` | does not fit beside `partkey` |

Only **Q17** needs exactly one LINEITEM index, and only Q17 fits — at 9.80 GB
resident. Q01 and Q06 each need two indexes on `l_shipdate`; Q15 needs three;
Q19 needs two; Q14 needs three. Every one of them exceeded the cap with the
datafile raised to the licence edge (`MAXSIZE 12200M`), failing with ORA-01652
rather than being estimated to fail.

So Oracle TPC-H indexed goes from 9 measured to 11, and 34 `not_run` to 32. The
remaining 32 are not a gap in effort. Two thirds of the budget is spent before a
single secondary index exists.

**A trap worth recording for anyone repeating this.** Oracle Free enforces the
cap against *allocated* datafile size, not used space, and it enforces it at PDB
open. A campaign that loads and drops working sets in sequence ratchets the file
upward while segments stay small; the database then runs fine until it is
restarted, and refuses to open. No open mode bypasses the check
(`READ ONLY`, `RESTRICTED` and `UPGRADE` all raise ORA-12954), and nothing that
shrinks a datafile can run against a closed PDB, so the only exit is
`ALTER DATABASE DATAFILE ... OFFLINE DROP` and losing the tablespace. This
happened here at 12.51 GB allocated against 5.44 GB resident. The tablespace is
now created with an explicit `MAXSIZE` for that reason.

## 11. Oracle Free's 12 GB is a whole-PDB limit, and UNDO counts against it

Entry 10 said the cap applies to *allocated* size rather than used space. That is
right but incomplete, and the incomplete version cost a full working set.

**The check sums every datafile in the PDB, not the user tablespace.** Measured
by hitting it: with `userdata01.dbf` at 11.91 GB and nothing else changed, the
PDB refused to open, because SYSTEM (0.29 GB) and SYSAUX (0.37 GB) push the
total past 12. So the usable ceiling for user data is not 12 GB but roughly
11.3 GB, and less once UNDO is counted.

**UNDO is the part that surprises.** Loading the group G working set with
`ROW STORE COMPRESS ADVANCED` grew `undotbs01.dbf` to **20.25 GB**. Advanced
compression on the conventional insert path generates undo in proportion to the
uncompressed row image, and the tablespace was created `AUTOEXTEND` with no
`MAXSIZE`, so it consumed the entire budget invisibly - the user tables were
only 9.63 GB. The PDB then failed to open on the next restart, and neither the
undo nor the datafile could be shrunk, because nothing that resizes a file runs
against a closed PDB.

The recovery is the same one entry 10 describes, applied twice:
`ALTER DATABASE DATAFILE ... OFFLINE DROP` for the oversized file, open, then
recreate. Every tablespace in this instance now carries an explicit `MAXSIZE`
chosen so the *sum* stays under the limit - 9000M for data, 2000M for undo,
against 0.66 GB of SYSTEM and SYSAUX.

**What this means for Q09 and Q20.** They remain `not_run`, and now for a
measured rather than an estimated reason. Compression worked: the working set
went from 12.37 GB uncompressed to **9.63 GB**, with LINEITEM 7.18 -> 5.65 GB,
ORDERS loading at all for the first time, and PARTSUPP at 1.33 GB. But the
LINEITEM primary key adds 1.25 GB, giving 10.88 GB of user data against a
practical ceiling near 9.3 GB once SYSTEM, SYSAUX and a bounded UNDO are
subtracted. **Compression closed most of the gap and not all of it.**

The four cells are therefore not reachable on Oracle Database Free by any
technique available here: not by scoping tables (entry 2), not by scoping
indexes (entry 10), and not by compressing (this entry). That is a property of
the licence, and it is the cleanest statement of the licence's cost that this
study can make.
