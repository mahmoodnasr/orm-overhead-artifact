# Environment: what each system was given, and what it actually runs on

The record a reviewer needs to answer "were the four systems compared on equal
terms?". Every number here was read off the running system or off the
configuration file named beside it, not recalled.

Two distinctions run through this document and are worth stating once:

**Allocation is not utilisation.** All four systems are *given* the same CPU,
memory and disk. They differ in how much of it one query can use, because
MySQL's executor is single-threaded and cannot be made otherwise. Allocation is
under our control; utilisation is a property of the engine.

**One machine.** Every measurement was taken on the Apple M4 below. An earlier
version of this file claimed a cloud sandbox that has since
been retired, and moved to a local machine. Which campaign ran where is recorded
per row in `results/all_results.csv` under `campaign_id`, and summarised at the
bottom of this file.

## The host

| | |
|---|---|
| Machine | Apple M4, 10 cores (4 performance + 6 efficiency) |
| Memory | 16 GB |
| OS | macOS 26.5.2, build 25F84 |
| Architecture | arm64 |
| Disk | 460 GB total, 95 GB free, NVMe |
| Container runtime | OrbStack, Docker Engine 29.4.0, overlayfs |
| Linux VM | 10 CPUs, 11.7 GB RAM |

The VM is the real ceiling: a container cannot see more than 10 CPUs or 11.7 GB
no matter what the host has.

## What each database is given

Identical, and declared in `docker-compose.yml` rather than left implicit. It
was equal before only because nothing constrained it, which is true but not
checkable.

| | PostgreSQL | MySQL | SQL Server | Oracle |
|---|---|---|---|---|
| `cpus` | 10 | 10 | 10 | 10 |
| `mem_limit` | 6 GB | 6 GB | 6 GB | 6 GB |
| `shm_size` | 4 GB | — | — | 2 GB |
| Disk | same volume, no quota | same | same | same |
| **Nominal data cache** | `shared_buffers = 3GB` | `innodb_buffer_pool_size = 4G` | `max server memory = 4096 MB` | **1.5 GB SGA — licence cap** |
| Per-operation workspace | `work_mem = 128MB` | InnoDB internal | inside the 4096 above | inside the SGA |
| **Measured peak container memory** | ~5 GB | ~4.5 GB | **4.89 GB** | not yet measured |

Only one database is ever resident at a time, so each
really does get all of it.

### The two "4 GB" settings are not the same quantity

This is the most important caveat on the whole table, and it is stated rather
than smoothed over because the configuration files make the four systems look
more equal than they are.

**SQL Server's `max server memory` caps total process memory** — buffer pool,
plan cache, query workspace grants and every other clerk. At 4096 MB, SQL
Server's whole footprint was measured at 4.89 GB.

**PostgreSQL's `shared_buffers` caps only the buffer cache.** `work_mem` is
charged per participant per node on top of it, `maintenance_work_mem` on top of
that, and because PostgreSQL uses buffered I/O the Linux page cache holds a
second copy of the data — which counts against the container's cgroup. Its total
is therefore `shared_buffers` + workspace + whatever page cache fits under
`mem_limit`, which is why the number in its configuration file has to be chosen
against a different target than SQL Server's.

MySQL sits with SQL Server rather than PostgreSQL here: `my.cnf` sets
`innodb_flush_method = O_DIRECT`, so InnoDB bypasses the OS page cache and its
footprint stays near its 4 GB buffer pool.

PostgreSQL's nominal cache is therefore 3 GB where the other two are 4 GB, and
that mismatch is deliberate: it is what makes the *totals* match instead of the
labels. At `shared_buffers = 4GB` the arithmetic did not fit. 4 GB of buffers
plus 1.15 GB of `work_mem` (9 participants x 128 MB for one parallel hash) is
5.15 GB of non-reclaimable memory inside a 6 GB container, leaving almost
nothing for page cache, and the kernel thrashed:
`/sys/fs/cgroup/memory.events` recorded the limit hit **503,365 times** during a
single validation pass, with no OOM kills but continuous reclaim. SQL Server
never met that constraint - its 4096 MB covers workspace as well as cache, so it
sat at 4.89 GB with headroom to spare. Running PostgreSQL under memory pressure
that its comparator did not experience is a worse inequality than a mismatched
label, so the label gave way. At 3 GB the total lands near 5 GB, close to SQL
Server's 4.89 GB, and the pressure disappears.

The residual gap was left rather than closed, deliberately. Closing it downward means
running PostgreSQL with essentially no OS page cache, which is not how
PostgreSQL is deployed anywhere and would make its absolute numbers
unrepresentative. Closing it upward means abandoning the 4096 = 4 GB match. What
makes leaving it defensible is scale: the dataset is about 21 GB, so neither
4.89 GB nor 6 GB caches it, both systems are I/O-bound against the same NVMe,
and the extra gigabyte shifts the cache hit rate identically for the ORM and the
SQL path — which is the only comparison this study draws from a single row.

### Oracle is not on equal terms, and cannot be put there

The one inequality in this study that no configuration can close, and it was
recorded wrongly here until it was checked: this document previously listed
Oracle as seeing 10 CPUs and running at parallel degree 8. Neither was ever
true. The container limit is 10 CPUs, but the *engine* sees 2 and has never run
a parallel query.

Oracle Database Free is licence-limited, and the software enforces it:

| | The other three | Oracle Free |
|---|---:|---:|
| CPU threads the engine uses | 10 | **2** |
| Data cache | 3–4 GB | **1.5 GB** (`sga_max_size`) |
| Parallel workers per query | 8 (1 on MySQL) | **1** |
| Maximum user data | unlimited | **12 GB** |

Raising them was attempted and refused:

    ALTER SYSTEM SET cpu_count=10            ORA-02097: specified value is invalid
    ALTER SYSTEM SET sga_max_size=4G         ORA-65040: not allowed from within a PDB
    ALTER SYSTEM SET parallel_max_servers=8  accepted, still reads 1 (derived from cpu_count)

So Oracle runs on roughly a fifth of the CPU and a third of the cache the other
three were given. **Its absolute times are not comparable with theirs, at all.**

The ORM-versus-SQL ratio within Oracle remains sound, because both arms run in
the same process against the same 2 CPUs — which is the comparison this study
draws from a single row, and the reason the Oracle rows are worth measuring
despite the inequality.

Paying for Standard or Enterprise Edition would lift the caps and would not
help: Oracle's commercial agreements carry the same benchmark-disclosure clause
as the developer licence, so a purchased licence does not by itself grant the
right to publish these numbers. The Free Use Terms covering this image do. That
is why the study uses the Free image, and it is a licensing decision before it
is a technical one.

### Why `mem_limit` is 6 GB and not the VM's full 11.7 GB

It was 11 GB, and that was wrong for the same reason. PostgreSQL was the only
engine free to take a second, unbounded cache: 4 GB of `shared_buffers` plus up
to 7 GB of page cache. The measured consequence on a 16 GB host was 0.1 GB free
with 4.5 GB of 5 GB swap in use while a campaign ran — the machine was swapping,
which corrupts timings on every system.

`work_mem` was halved from 256 MB to 128 MB at the same time and for a related
reason: it is charged per participant, so raising parallelism from 2 workers to
8 took a single parallel hash join from 3 x 256 MB = 768 MB to 9 x 256 MB =
2.3 GB. That both exceeded the container's `/dev/shm`, where PostgreSQL places
the dynamic shared memory a parallel hash lives in — Q04 and Q21 failed
validation with *"could not resize shared memory segment"*, a segment asking for
exactly 2 GB against a 2 GB tmpfs — and quietly widened the memory gap above.
`shm_size` for PostgreSQL is 4 GB for the same reason; it is a hard ceiling on
intra-query parallelism, not a tuning knob.

## What each database actually runs

| | PostgreSQL 14 | MySQL 8.0 | SQL Server 2019 | Oracle Free 26ai |
|---|---|---|---|---|
| Image | `postgres:14` | `mysql:8.0` | `mcr.microsoft.com/mssql/server:2019-latest` | `gvenzl/oracle-free:23-slim` |
| Version | 14 | 8.0.46 | 15.0.4480.2 CU32-GDR | **26ai Free 23.26.2.0.0** |
| Edition | — | Community | **Developer** | Free |
| Architecture | native arm64 | native arm64 | **linux/amd64 under emulation** | native arm64 |
| CPUs the engine sees | 10 | 10 | 10 (10 schedulers) | **2 — licence cap** |
| Storage engine | heap + B-tree | **InnoDB** | heap + B-tree | — |
| Parallelism setting | `max_parallel_workers_per_gather = 8` | none available | `MAXDOP 8` | **none possible** |
| **Threads per TPC-H query** | 8 (+leader) | **1** | 8 | **1** |
| TPC-H SF10 on disk | 21 GB *with* indexes | ~22 GB *with* indexes, estimated | 14.4 GB *without* indexes, measured | 10.81 GB *without* indexes, measured |

The size row is not like-for-like and is left that way rather than tidied into a
false comparison: two of the four figures include the secondary indexes and two
do not, and MySQL's is an estimate rather than a measurement because its data
volume no longer exists to be measured. The only figure to rely on for a
capacity decision is Oracle's, which is the one the 12 GB edition cap turns on.

Three of these need saying out loud.

**SQL Server runs under x86-64 emulation.** There is no arm64 build of the
image. It works and it is stable, but its absolute times carry an emulation
penalty that the other three do not. Its ORM-versus-SQL ratios are unaffected —
both arms run in the same process against the same server.

**MySQL runs every TPC-H query on one thread.** Not a configuration choice and
not fixable. `innodb_parallel_read_threads = 8` was measured to make
`SELECT COUNT(*)` 4.4x faster (0.40 s -> 0.09 s) and to make a `GROUP BY` with
aggregation and a sort *slower by noise* (1.64 s -> 1.69 s), because MySQL's
executor above the storage engine is single-threaded by design. The full
evidence and the three structural workarounds, with why none is usable here, are
in `docs/PARALLELISM.md`.

**MySQL is InnoDB, and that is not neutral.** InnoDB always clusters a table on
its primary key and cannot be told not to, so MySQL's *non-indexed*
configuration has an ordered access path PostgreSQL's heap does not. This is why
`lineitem` carries no primary key in any of the three schemas, and why SQL
Server's primary keys are declared `NONCLUSTERED` — to match PostgreSQL's
heap-plus-B-tree rather than MySQL's forced clustering. See
`scripts/1-setup/schema_mysql.sql` and `schema_sqlserver.sql`.

Oracle is additionally constrained by its edition: Oracle Free caps user data at
12 GB, and TPC-H SF10 loads to 10.81 GB, so the dataset fits and its indexes do
not. It is measured per query group over only the tables each group references
(`scripts/1-setup/oracle_groups.py`).

## Reading resource usage: `docker stats` is not trustworthy here

Worth recording because it caused a false alarm and would cause another.

`docker stats` reported PostgreSQL at 619%, 2686% and 2732% CPU in three
consecutive samples. On a 10-core machine anything above 1000% is impossible, so
those numbers are artefacts. It derives CPU from a cgroup counter delta over a
very short sampling window, and PostgreSQL forks a fresh set of parallel workers
*per query*, so the bursts inflate the delta relative to the interval. The VM
layer on macOS makes it worse.

Measure it these ways instead, all of which agreed:

| Method | Reading |
|---|---|
| `docker stats` | 619–2732% — unusable |
| `ps -eo pcpu` summed inside the container | **736–973%** |
| `pg_stat_activity` active backends | **9** = 1 leader + 8 parallel workers |
| Host `top`, 10 cores | 67% idle |

Nine backends on ten cores is exactly what
`max_parallel_workers_per_gather = 8` should produce, so the configuration was
confirmed working — by the process count, not by the percentage.

The memory column of `docker stats` is more reliable but still needs reading
carefully: it reports `memory.current` minus reclaimable file cache, so for
PostgreSQL it understates the cache the container is actually holding. The
cgroup breakdown in `/sys/fs/cgroup/memory.stat` — `anon`, `file`, `shmem` — is
what to quote.

## Measurement protocol

### TPC-H

| | |
|---|---|
| Scale factor | TPC-H SF10, 59,986,052 lineitem rows |
| Data source | DuckDB `tpch` extension, fixed seed, same file for all four |
| Repetitions | 4 per path; **first discarded as warmup**, median of the remaining 3 |
| Statement ceiling | 900 s |
| Paths per query | 4 — Django ORM, Django SQL, SQLAlchemy ORM, SQLAlchemy SQL |
| Validation | 5 checks, all must pass before a timing is kept |

### TPC-C

Measured two ways, because the two answer different questions and neither
substitutes for the other. The paper states its TPC-C results as throughput;
this study's ORM-overhead argument needs latency.

| | Latency (`run_tpcc.py`) | Throughput (`run_tpcc_throughput.py`) |
|---|---|---|
| Clients | 1 | **50** |
| Unit | median seconds per transaction | transactions per minute |
| Repetitions | 4, first discarded | 60 s counted after 10 s warmup |
| Paths | 4 per transaction | 4 per transaction |
| In the 432-row grid? | **yes** | **no** — needs concurrency as a dimension |

Scale is 10 warehouses: 10 x 10 districts x 3,000 customers, 100,000 items,
4,889,141 rows, 926 MB. Generated by `scripts/1-setup/load_tpcc.py` from a fixed
seed (default 42) and streamed straight in — the previous generator called
`random.randint` unseeded, so TPC-C was not reproducible even in principle.

Note what that size means: **the whole database fits in every system's cache**,
so TPC-C here measures in-memory transaction cost with essentially no I/O. That
is arguably the right condition for isolating ORM overhead, and it is not a
throughput result for a disk-bound system.

Two protocol details that exist because of measured failures. Every schema is
reloaded from the seeded generator before it is measured, because a 60-second
Payment path inserts over 100,000 history rows and comparing a schema measured
on grown data against one measured on fresh data would confound the index effect
with a dataset change. And `new_order` is refilled before every Delivery path:
Delivery consumes rows nothing else replaces at that rate, and it drained the
table from 105,020 to 2,439 mid-run, after which it was measuring an empty table
at speed. A run that starves anyway is marked INVALID in its own note.

The 900 s ceiling is applied server-side where the vendor has one
(`SET statement_timeout`, `SET SESSION max_execution_time`) and on the client
connection where it does not — Oracle's `call_timeout` and SQL Server's pyodbc
`timeout`, both set on *both* frameworks' connections. See defect C13 for what
happened when only one framework got it.

## Which campaign ran on which machine

| Campaign | Machine | Parallelism | Memory config | State |
|---|---|---|---|---|
| SQL Server non-indexed | localhost M4 | MAXDOP 8 | 4096 MB, peak 4.89 GB | **done**, 88/88 |
| SQL Server indexed | localhost M4 | MAXDOP 8 | 4096 MB | **done** |
| MySQL indexed | localhost M4 | 1 | 4 GB buffer pool | done, 88/88 |
| MySQL non-indexed | sandbox (retired) | 1 | 4 GB buffer pool | done, 16 timeouts |
| Oracle non-indexed, 8 cells | sandbox (retired) | default | default SGA | partial, 8/88 |
| PostgreSQL non-indexed | localhost M4 | 8 workers | 4 GB + 128 MB work_mem, 6 GB cap | **re-measuring** |
| PostgreSQL indexed | localhost M4 | 8 workers | as above | queued |
| *superseded:* PostgreSQL both schemas | sandbox (retired) | 2 workers | 4 GB + 256 MB work_mem | archived under `measurements/superseded/` |

The PostgreSQL rows are being re-measured because the original pair ran at
PostgreSQL 14's default of 2 workers per gather while SQL Server ran at MAXDOP
8 — unequal per-query CPU. The originals are kept in
`results/corrected/measurements/superseded/`, which `load_measurements()` never
reads, so they cannot reach the results file.

The sandbox was a cloud container with roughly 24 GB of disk and one database
resident at a time. It is gone, and so are the PostgreSQL and MySQL data volumes
that were on this machine — only the SQL Server volume survives. The dataset is
regenerable from `tpch10.duckdb` (2.5 GB, kept), and every measurement is in
`results/corrected/measurements/*.csv`, which is committed.

`campaign_id` on each row of `results/all_results.csv` carries this, and
`make_all_results.py` adds an explicit warning to any row whose
indexed-versus-non-indexed comparison spans two machines — MySQL's, currently.

## What this permits and forbids

**Permitted, and the point of the study.** ORM versus hand-written SQL within
one (DBMS, schema, query). Both arms run in the same process, against the same
server, under the same settings, on the same machine, in the same campaign.
Nothing above touches this comparison.

**Forbidden without stating the caveat.** Comparing overhead *across* systems.
Overhead is a ratio; the ORM's cost is largely fixed per row while the database's
is not, so a database half that runs eight times faster raises the ORM's share of
the total. "SQL Server shows more ORM overhead than MySQL" would be partly a
statement about MAXDOP 8 versus MySQL's single thread, and partly about
emulation. Absolute times are not comparable across the four systems at all.
