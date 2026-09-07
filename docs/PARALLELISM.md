# Parallelism across the four systems

A finding, not a defect, and one that belongs in the paper rather than only in
the configuration files. It constrains what the cross-DBMS comparison in this
study can claim, and the constraint comes from MySQL's architecture rather than
from anything this package does.

## The finding

**In standard MySQL, a single query is strictly single-threaded — including one
with the complex joins every TPC-H query has.** MySQL's optimiser cannot split
join processing or aggregation across CPU threads for one connection. Setting
`innodb_parallel_read_threads = 8` speeds up raw clustered-index scans for basic
counts and DDL, and does nothing whatever for query execution.

This was measured rather than assumed, because the obvious first suspicion is a
misconfiguration on our side. MySQL 8.0.46, 8,000,000 rows, one server, one
table, `innodb_parallel_read_threads` the only variable changed, best of three:

| Query | `threads = 1` | `threads = 8` | Effect |
|---|---:|---:|---|
| `SELECT COUNT(*) FROM big` | 0.40 s | **0.09 s** | 4.4x faster |
| `SELECT g, SUM(v), AVG(v), COUNT(*) … GROUP BY g ORDER BY 2 DESC` | 1.64 s | **1.69 s** | none |

And by peak CPU, on the same server:

| Query shape | Peak CPU |
|---|---:|
| `COUNT(*)`, no WHERE | 188% |
| `GROUP BY` + aggregate + sort — TPC-H Q01 shape | 103% |
| hash join + aggregate — TPC-H Q03 shape | 100% |

So the setting is not being ignored: it works, and it demonstrably uses the
threads it is given. It simply cannot reach the operators TPC-H is made of.

The reason is structural. `innodb_parallel_read_threads` is a *storage engine*
setting; it parallelises the scan of a clustered index and feeds rows upward.
MySQL 8.0's executor — the layer performing joins, `GROUP BY`, aggregation and
sorting — is single-threaded by design. There is no parallel join, no parallel
aggregate and no parallel sort anywhere in the product. The setting can
therefore only help operations that are *nothing but* a scan: `COUNT(*)` with no
`WHERE`, `CHECK TABLE`, and index builds. All twenty-two TPC-H queries contain a
join, a `GROUP BY` or a sort, so all twenty-two run on one core, and no setting
changes that.

The only other `*parallel*` variables MySQL 8.0 exposes are
`replica_parallel_workers` / `replica_parallel_type` and their deprecated
`slave_` aliases. Those are replication apply threads and have nothing to do
with query execution.

## Three ways to get eight-way parallelism out of MySQL, and why none is used here

These are the structural approaches available. Each was considered and each
would change what the study measures, which is why the limitation is reported
instead.

**1. Inter-query parallelism — the standard TPC-H answer.** TPC-H is specified
with two metrics: Power, the single-query latency this study measures, and
Throughput, concurrent query streams. Eight-way parallelism is reached by firing
eight distinct streams at once:

```bash
seq 1 8 | xargs -P 8 -I {} mysql -u user -p -D tpch -e "SOURCE q{}.sql;"
```

Not applicable here. This study times one query at a time on purpose: ORM
overhead is a per-query latency question, and running eight streams would
measure queueing and contention rather than the cost of object materialisation.
It would also make MySQL's numbers incomparable with the other three systems,
which are measured serially.

**2. Table partitioning — intra-query parallelism by hand.** Chunk the workload
at the application layer, splitting `LINEITEM` or `ORDERS` by a modulo of the
primary key, running the eight fragments as background processes and combining
them with `UNION ALL` or in the application:

```sql
-- thread 1
… WHERE MOD(l_orderkey, 8) = 0
-- thread 2
… WHERE MOD(l_orderkey, 8) = 1
```

Not applicable here, and it would be actively wrong. Only some TPC-H queries
decompose this way — anything with a global `GROUP BY`, a correlated subquery or
a `HAVING` over the full set does not partition cleanly, and Q13's
double aggregation and Q15's global maximum do not partition at all. More
importantly, the recombination step would be *framework code*, so Django and
SQLAlchemy would be timed executing a hand-written parallelisation strategy
rather than the query. That is a variant of defect C1.

**3. MySQL HeatWave.** An in-memory hybrid accelerator built for exactly this:
massively parallel processing of multi-table TPC-H joins. It genuinely solves
the problem.

Not applicable here for two reasons. It is a managed Oracle Cloud service rather
than something reproducible from this repository's `docker-compose.yml`, which
would break the reproducibility package. And it is a different query engine, so
"MySQL" in the results would no longer mean the same product as the MySQL
everyone else runs — the comparison would silently become one against a
columnar MPP engine.

## What is configured, and what it means for the comparison

Resource *allocation* is identical across all four systems and declared in
`docker-compose.yml`: the same CPU count, the same memory ceiling, the same
disk. The engine data cache is 4 GB in each of the three configuration files.
That much is exact.

Per-query CPU *utilisation* cannot be made identical, because MySQL is a floor
that cannot be raised. Parallelism is therefore set to 8 on the three systems
that support it, and MySQL runs at the 1 it is capable of:

| System | Setting | Threads per query |
|---|---|---:|
| PostgreSQL 14 | `max_parallel_workers_per_gather = 8` | 8 |
| SQL Server 2019 | `MAXDOP 8` | 8 |
| Oracle Free 23ai | parallel degree 8 | 8 |
| MySQL 8.0 | none available | **1** |

One semantic difference to keep in mind when reading those numbers: SQL Server's
MAXDOP counts total threads for a parallel branch, whereas PostgreSQL's
`max_parallel_workers_per_gather` counts background workers *excluding* the
leader, and the leader also participates by default. PostgreSQL at 8 can
therefore put up to nine processes on a query where SQL Server puts eight.

**What this does not affect.** Every ORM-versus-SQL comparison in this study.
Both arms of every such comparison run in the same process, against the same
server, under the same settings, so the overhead figure in any single row is
unaffected by any of the above.

**What this does affect.** Comparison of overhead *across* systems. Overhead is
a ratio, and the ORM's cost is largely fixed per row while the database's cost
is not. When the database half runs eight times faster, the ORM's share of the
total rises. So a sentence like "SQL Server shows more ORM overhead than MySQL"
would be partly a statement about parallelism rather than about the frameworks,
and must not be written without this caveat. MySQL's absolute times will also be
the slowest of the four for reasons that have nothing to do with either ORM.
