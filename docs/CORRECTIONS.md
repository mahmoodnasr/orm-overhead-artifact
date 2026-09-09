# Corrections

Historical register retained from v1.0.1. Earlier campaign figures and commands
below are historical context; the current public workflow is in the root README
and REPRODUCE.md. This register does not establish equivalence for every
historical SF1 timing.

What was wrong in the earlier version of this package, how it was found, and what
changed. Recorded here rather than quietly fixed, because the failures are
instructive and because anyone holding a figure from the earlier version needs to
know it is not usable.

## C1 — SQLAlchemy was not running through the ORM

In 18 of the 22 query modules, `run_query_orm` called `run_query_sql` directly:

```python
def run_query_orm(session: Session):
    # For now, delegate to SQL version for consistency with benchmarks
    return run_query_sql(session)
```

The harness called `run_query_orm` to measure the ORM and `run_query_sql` to
measure the baseline, so for those 18 queries it timed the same function twice
and reported the difference as ORM overhead. Only Q1, Q2, Q3 and Q6 had genuine
ORM implementations.

This is why the earlier SQLAlchemy overhead figures clustered near zero and why
the object-materialization columns were zero for those rows: no objects were ever
constructed.

**Fixed.** All 22 queries now have genuine SQLAlchemy ORM implementations built
from the mapped classes in `sqlalchemy_app/models.py`. No `text()` literal
appears in any ORM path. `scripts/validate_queries.py` checks this mechanically.

## C2 — the two frameworks were not running the same queries

Every SQLAlchemy query taking a date range bound it to a single hard-coded
window, 1995-01-01 to 1997-01-01, regardless of what the specification says for
that query. The files still carried the unused per-query parameters
(`date_start_q12`, `date_start_q14`, `date_start_q20`) from the template they
were generated from, but the SQL template referenced only `{date_start}` and
`{date_end}`.

| Query | Specification window | Used | Data scanned |
|---|---|---|---:|
| Q4 | 3 months | 2 years | ~8× |
| Q10 | 3 months | 2 years | ~8× |
| Q14 | 1 month | 2 years | ~24× |
| Q15 | 3 months | 2 years | ~8× |
| Q5, Q12, Q20 | 1 year | 2 years | ~2× |

Django used the correct per-query windows throughout. The frameworks were
therefore being compared on different workloads.

**Fixed.** `sqlalchemy_app/queries/_sql.py` carries the specification's
parameters per query. Validation check 3 compares the two baselines' results.

## C3 — two Django implementations were incorrect

**Q9** omitted the `partsupp` join and summed revenue where TPC-H asks for
profit. The file's own comment recorded the omission: *"This is simplified. Full
implementation needs PartSupp join for supplycost."* It also used `icontains`,
which emits a case-insensitive `ILIKE`, where the specification says
`LIKE '%green%'`.

**Q13** chained `.annotate(custdist=Count('*'))` onto a queryset that had already
annotated an aggregate. Django collapsed the grouping and returned a single row
where the query defines a 42-row distribution. Its predicate was also wrong:
`~Q(comment__icontains='special') & ~Q(comment__icontains='requests')` excludes
comments containing *either* word, where the specification excludes
`'%special%requests%'`.

**Fixed.** Q9 expresses the supplycost lookup as a correlated `Subquery` on the
(partkey, suppkey) pair. Q13 moves the per-customer count into a correlated
`Subquery` so it stays a scalar expression the outer query can group by. Both
verified against their own SQL baselines.

## C4 — the overhead decomposition was arithmetic, not measurement

`run_benchmark_multi_orm.py` profiled the ORM call path, then discarded the
profiled component times unless they reproduced the residual within 15 %, and
substituted:

```python
adjusted['query_construction'] = min(2.0, expected_overhead * 0.05)
adjusted['execution']          = 0.4
adjusted['fetching']           = 0.7 * (1 + math.log10(max(row_count, 1)) / 10)
adjusted['conversion']         = expected_overhead * 0.08
adjusted['materialization']    = max(0, expected_overhead - accounted)
```

The fallback was the normal path: 332 of 352 rows carry `network_roundtrip`
exactly `0.4`, and 280 satisfy `materialization = residual − others` exactly.
Object materialization was defined as the remainder, so it was guaranteed to
dominate whatever the truth.

**Fixed.** Overhead is now a measured two-way split, ORM time against
hand-written SQL time, and nothing finer. Row count is reported alongside so a
reader can judge whether object construction is a plausible explanation for a
given result. The harness that produced the synthesised columns has been
retired.

## C5 — two harness bugs found during the corrected campaign

A failure in one access path aborted the remaining three for that query, so a
single Django SQL timeout discarded both SQLAlchemy measurements and left 14
holes in the design grid. And a failed statement left the SQLAlchemy session in
an aborted transaction, so the next path reported *current transaction is
aborted* — a contaminated measurement rather than a real one.

**Fixed.** Paths are independent, and a failure rolls the connection back and
re-arms the statement timeout before the next path runs.

## C6 — Q11's threshold was held at the SF1 constant

TPC-H Q11 selects parts whose stock value exceeds a fraction of the national
total. Almost every substitution parameter in the validation set is a constant,
and this one is not: the specification defines FRACTION as 0.0001/SF, so it has
to shrink as the database grows.

All three implementations — the hand-written baseline, the SQLAlchemy ORM
construction and the Django ORM construction — carried 0.0001. At SF10 the
German stock total is 810,291,376,524, so the threshold that constant produces
is 81,029,137, which no individual part reaches. Q11 returned an empty result in
all eight PostgreSQL cells.

It is a quiet failure. The query still scans PARTSUPP, still joins, still
aggregates and still sorts, so it takes a plausible amount of time and the
harness records it as a successful measurement — of a query that is not Q11.

**Fixed.** `tpch_params.py` derives FRACTION from `TPCH_SF`, and both frameworks
and both access paths read it from there so they cannot drift apart. The eight
affected PostgreSQL rows are marked in `results/all_results.csv` and must be
re-measured.

## C7 — Oracle: CHAR columns silently emptied every ORM result

Oracle applies blank-padded comparison semantics only when *both* operands are
CHAR. A bind variable is VARCHAR2, so `r_name = :1` against `CHAR(25)` compares
`EUROPE` against `EUROPE` followed by nineteen spaces and matches nothing, while
the identical predicate written as a literal matches, because a literal against
CHAR is blank-padded.

The hand-written baselines inline their literals; the ORMs bind. So on Oracle,
Q2 returned 100 rows through both raw-SQL paths and 0 rows through both ORM
paths — with no error, and with the frameworks agreeing perfectly with each
other.

PostgreSQL and MySQL both ignore trailing blanks when comparing CHAR, so
declaring these columns VARCHAR2 is what makes Oracle agree with the other three
systems rather than diverge from them. It also removes the padding from storage,
which on this dataset is worth 1.38 GB — 12.19 GB down to 10.81 GB — and under
Oracle Free's 12 GB ceiling that is not a rounding error.

**Fixed** in `schema_oracle.sql`.

## C8 — the validation harness had a blind spot

The three original checks compared ORM against ORM and baseline against
baseline. Neither compared an ORM path against its own SQL baseline, so a fault
that hit both ORM paths identically was invisible — which is exactly what C7
was: all three checks passed on the query that was returning nothing.

Nor did anything check that a query returned rows at all, which is what let C6
through.

**Fixed.** `scripts/validate_queries.py` now runs five checks per query: the ORM
path emits ORM-built SQL, the two frameworks agree, the two baselines agree, the
ORM result equals the SQL result, and the result is non-empty.

## C9 — four Django queries ran a different quarter on Oracle

`django_app/queries/q05.py`, `q12.py`, `q14.py` and `q15.py` build their raw SQL
with a per-vendor branch, because the date-literal syntax differs between
systems. Every branch carried the specification window except the Oracle one,
which in all four files was pinned to `1993-07-01` / `1993-10-01` — Q4's window,
copied and never changed.

So on Oracle, Q15 asked for the top supplier of the third quarter of 1993 while
every other system asked for the first quarter of 1996, and returned supplier
55,987 with revenue 2,331,435.38 against the correct 69,998 with 2,194,132.82.
The other three paths agreed with each other, so only a check comparing the ORM
result against its own SQL baseline could see it — which is the check C8 added.

**Fixed.** All four Oracle branches now carry their own query's window; only the
literal syntax differs.

## C10 — TPC-C: three asymmetries aligned, and what alignment exposed

The two TPC-C implementations differed in three ways that had nothing to do with
the frameworks, so measuring them as written compared those three choices:

*Key ranges.* Every transaction in both frameworks drew `w_id` from
`randint(1, 10)` with the range written into each file. All ten modules now draw
from `tpcc_config`.

> **Correction to this paragraph.** It previously read "while the database holds
> 100 warehouses", and concluded that every worker was confined to a tenth of the
> database. That is wrong. `scripts/1-setup/generate_tpcc_data.py` sets
> `NUM_WAREHOUSES = 10` and is the only TPC-C generator in the repository; no
> loader here builds 100 warehouses. On the database this code actually loads,
> `randint(1, 10)` was the correct range and there was no contention defect. The
> centralisation still matters, but for the opposite reason: a config claiming
> 100 warehouses against ten loaded ones makes nine of every ten transactions
> fail on a missing row, and — before the fix below — Django would have reported
> each of those failures as a completed transaction. `tpcc_config.verify_against()`
> now checks the constants against the loaded row counts and raises on a
> mismatch. Call it before measuring.

*Locking policy.* SQLAlchemy's New-Order took `SELECT ... FOR UPDATE` on the
district row on its ORM path; Django did an unlocked read, and SQLAlchemy's own
raw-SQL path took no lock either. Both frameworks and both paths now honour
`tpcc_config.LOCK_DISTRICT`.

*Transaction boundary.* Django ran statement by statement in autocommit;
SQLAlchemy wrapped the work in one commit — except in T3 and T5, which never
committed or rolled back at all. Both now open one explicit transaction per
business transaction.

**What alignment exposed, which matters more than the alignment itself.** Two of
these were reasons the TPC-C numbers could not be reported as they stood. Both
are now fixed; they are kept here because each was invisible in the numbers.

*Neither raw-SQL New-Order wrote ORDER_LINE.* `run_transaction_sql` in both
frameworks inserted into ORDER and NEW_ORDER and stopped. It never read ITEM or
STOCK and never wrote an order line. It was roughly a third of a New-Order, so
"T1 SQL" was not New-Order and was not comparable to "T1 ORM" — and because the
missing two thirds were work the *ORM* path did perform, the defect inflated
measured ORM overhead rather than producing an obvious error.

**Fixed.** Both raw-SQL paths now mirror their own framework's ORM path
statement for statement and in the same order: they read WAREHOUSE and CUSTOMER,
take the district row under `LOCK_DISTRICT`, write ORDER and NEW_ORDER, and then
run the order-line loop, reading ITEM and STOCK and inserting one ORDER_LINE per
line. The per-line draws happen in the same order as the ORM path, so both paths
consume the same values from `random` and touch the same rows. The two
`if vendor == 'oracle'` branches around the ORDER insert, whose bodies were
identical, were collapsed — the timestamp difference they appeared to handle is
already carried by `get_current_timestamp`.

*Django's ORM paths swallowed every exception* — `except Exception as e: return
{'error': str(e)}` — while SQLAlchemy propagated. A harness that counts a
returned dict as success records Django's failed transactions as completed ones
and its error rate as zero. It also hides deadlocks and serialization failures,
which are precisely what a locking study needs to see. The Django raw-SQL paths
had no such handler, so Django was inconsistent with itself as well.

**Fixed.** All five Django ORM paths now re-raise. The `transaction.atomic`
block has already rolled back by the time the handler runs, so the only change is
that a failure is now reported as one. The two raw-SQL early returns that carried
`{'error': 'District not found'}` raise `LookupError` for the same reason, as do
the new WAREHOUSE, CUSTOMER, ITEM and STOCK lookups — a key drawn outside the
loaded range is a configuration error, and `tpcc_config.verify_against()` exists
to catch it before a campaign starts rather than one row at a time.

Three further differences are arguably the result rather than defects, and are
recorded so they are not mistaken for framework overhead. Delivery issues one
bulk UPDATE in Django and one UPDATE per order line in SQLAlchemy — roughly 1
against 100 statements per transaction, which will dominate T4. Payment and
New-Order use `F()` expressions in Django and Python-side read-modify-write in
SQLAlchemy, which is equivalent under `LOCK_DISTRICT=True` and can lose updates
without it. Stock-Level reads the district row in Django and not in SQLAlchemy,
so Django issues four SELECTs against SQLAlchemy's three.

## C11 — the SQL Server dialect branch emitted invalid SQL

`sql_for()` in `sqlalchemy_app/queries/_sql.py` adapted the ANSI statements to
each vendor. Its SQL Server branch contained:

```python
sql = sql.replace("EXTRACT(YEAR FROM ", "YEAR((").replace("))", "))")
```

The first replacement opens two parentheses and closes one, so
`EXTRACT(YEAR FROM o_orderdate)` became `YEAR((o_orderdate)`. The second
replacement substitutes `))` for `))` and does nothing whatsoever. Q07, Q08 and
Q09 are the three TPC-H queries that extract a year, and on SQL Server all three
were unbalanced and would have failed on first execution.

**Fixed.** The construct is matched as a whole,
`re.sub(r"EXTRACT\(YEAR FROM ([^)]+)\)", r"YEAR(\1)", sql)`, the same approach
the Oracle branch already used for its alias problem. All 22 statements now
balance in all four dialects.

This one is different from C1–C10 in that it had not yet reached a result: it
was found before the first SQL Server campaign, so no published number depends
on it. It is recorded because of *when* it was found. The defect sat in the
repository through every earlier audit, and the reason none of them saw it is
that the SQL Server path had never been executed — the same reason C6 and C7
survived until the Oracle port. A dialect branch that nothing runs is not code
that works; it is code whose behaviour is unknown, and it should be read as
untested until a validation pass says otherwise.

C12 through C17 are what that first execution then turned up: six more, in the
schema, the harness, two hand-written baselines and two ORM implementations.

## C12 — the SQL Server database was never created

`docker-compose.yml` mounted `docker/sqlserver/setup.sql` at
`/docker-entrypoint-initdb.d/setup.sql`. That path is a convention of the
PostgreSQL and MySQL images; `mcr.microsoft.com/mssql/server` has no
init-directory mechanism and ignores whatever is placed there. The file was
present inside the container, readable, and never executed.

The container therefore reported `healthy` — its healthcheck runs `SELECT 1`
against the server, which was genuinely up — while holding only `master`,
`tempdb`, `model` and `msdb`. The database `tpch`, the `tpch_user` login, the
memory ceiling and the MAXDOP setting were all absent. The first symptom a user
would meet is Django failing to open database "tpch", which reads as the server
being unreachable rather than as an init script that never ran.

**Fixed.** `scripts/1-setup/init_sqlserver.sh` applies the file explicitly and
then verifies the database exists, raising rather than exiting 0 if it does not.
`setup.sql` says in its own header that it is not self-applying. Two settings in
it were also wrong for this host and are corrected there with the reasoning:
`max server memory` was 8 GB on a VM with 11.7 GB total, against a 4 GB data
cache on each of the other two systems.

## C13 — SQL Server bounded one framework and not the other

`set_timeouts()` in `scripts/2-benchmark/run_query.py` mapped PostgreSQL to
`SET statement_timeout` and MySQL to `SET SESSION max_execution_time`, and had:

```python
"mssql": None,          # SQL Server uses a client-side query timeout
"sqlserver": None,
```

The comment is correct and nothing acted on it. SQL Server has no session-level
statement timeout to `SET`; the ceiling has to be placed on the client
connection. Django picked one up anyway, from `OPTIONS["query_timeout"]` in
`settings_sqlserver.py`. SQLAlchemy is built from `SA_DSN` and picked up
nothing.

So the two paths under comparison would have run under different rules: an ORM
query could run unbounded while its own hand-written baseline was cut off at the
budget, or the reverse, depending on which framework the harness was timing.
A timeout that applies to one arm of a comparison and not the other does not
just lose a cell — it biases the cell it keeps. `arm_timeout()` in
`scripts/validate_queries.py` had the same hole, and there `sqlserver` fell
through the vendor lookup entirely, so validation ran with no ceiling at all.

**Fixed.** Both functions now set `raw.timeout` on both raw pyodbc connections,
the same way the Oracle branch sets `call_timeout` on both, so the ceiling is a
property of the campaign rather than of which framework happens to be running.

Like C11 this had not reached a result — no SQL Server campaign had been run.
Both were found the same way: by executing a path that had only ever been read.

## C14 — mssql-django silently rewrote three LIKE patterns

`CursorWrapper.execute` in `mssql/base.py` reads:

```python
def execute(self, sql, params=None):
    self.last_sql = sql
    if 'GROUP BY' in sql:
        sql, params = self.format_group_by_params(sql, params)
```

and `format_group_by_params` begins `query = re.sub(r'%\w+', '{}', query)`. The
intent is to convert Django's `%s` placeholders; the effect is to convert *any*
`%` followed by word characters, anywhere in the statement, including inside a
string literal. It fires on any SQL containing the substring `GROUP BY`.

Three of the twenty-two hand-written Django baselines contain both a `GROUP BY`
and a LIKE pattern of that shape:

| Query | Pattern | Reached the server as |
|---|---|---|
| Q09 | `p_name LIKE '%green%'` | `LIKE '{}%'` |
| Q13 | `o_comment NOT LIKE '%special%requests%'` | `LIKE '{}{}%'` |
| Q16 | `s_comment LIKE '%Customer%Complaints%'` | `LIKE '{}{}%'` |

Read directly out of Query Store rather than inferred. `'MEDIUM POLISHED%'` and
`'forest%'` are untouched, because their `%` is followed by a quote.

None of the three raised. Q09 returned zero rows in 0.74 s, which the harness
would have recorded as a fast successful measurement. Q13 returned a complete,
plausible 46-row distribution that was simply the wrong distribution — its join
condition excluded almost nothing. Q16 returned 27,840 rows with its exclusion
subquery disabled. Only the `SQL=` check, which compares the two frameworks'
baselines against each other, showed anything at all.

**Fixed.** Each pattern is written as concatenation — `'%' + 'green' + '%'` —
so every `%` is followed by a quote and that regex has nothing to match. SQL
Server folds the constants at compile time, so the plan is the literal's plan.
Q09 and Q16 get per-vendor modules for this; Q13 needed one anyway (C17).

## C15 — Q15's Django ORM returned nothing on SQL Server

`q15.py` declares the summed revenue as
`DecimalField(max_digits=15, decimal_places=2)`. `l_extendedprice` and
`l_discount` are both `DECIMAL(15,2)`, so `extendedprice * (1 - discount)` has
scale 4 and the maximum revenue at SF10 really is `2194132.8166`. The declared
scale was always wrong.

PostgreSQL never charged for it: its backend overrides
`adapt_decimalfield_value` to pass `Decimal` values through untouched.
mssql-django uses Django's default, which quantises a bound parameter to the
declared `decimal_places`. So Q15 read the maximum back correctly as
`2194132.8166`, then sent it to the server as `2194132.82`, which equals no
group's total. Django's Q15 returned zero rows while the other three paths
returned the one correct row.

**Fixed** in the SQL Server module, as `DecimalField(max_digits=25,
decimal_places=4)`. Scoped there rather than in the shared module because
changing the shared declaration would touch three systems whose measurements
are already collected, and on those three the value passes through unquantised
regardless.

## C16 — Q09's SQL Server ORM summed the wrong quantity

`q09_sqlserver.py` carried its own ORM implementation which computed
`l_extendedprice * (1 - l_discount)` and stopped there. TPC-H Q9 sums *profit*:
that term **minus** `ps_supplycost * l_quantity`. The module never joined
PARTSUPP at all, and said so in its own comments — "Note: This is simplified.
Full implementation needs PartSupp join for supplycost".

It returned the right shape: 175 rows, right nations, right years, correctly
sorted, in a time indistinguishable from a correct run. Only the values were
wrong, by about 1.5x — ALGERIA/1998 came out at 414,006,807.63 against the
271,504,046.55 that the two baselines and the SQLAlchemy ORM agreed on. This is
the same class as C3, and it survived because the SQL Server path had never run.

**Fixed.** The correct query, reaching PARTSUPP by a join rather than by the
correlated `Subquery` the shared module uses — SQL Server rejects a subquery
inside an aggregated expression outright (error 130), so the shared
implementation cannot simply be imported.

## C17 — Q13 is not expressible through the Django ORM on SQL Server or Oracle

Not a defect in this repository, and the only entry here that is not fixed,
because it cannot be. It is recorded because the alternative to recording it is
publishing a number for a cell that was never measured.

Q13 aggregates twice — orders per customer, then customers per distinct count —
and the outer grouping is over the result of the inner one, which in SQL is a
derived table. Django's ORM has no derived-table construct; its only route is
`Subquery` in an annotation, which is what the shared `q13.py` uses and what
works on the other three systems. SQL Server does not permit a subquery in a
GROUP BY expression, and mssql-django states it: `supports_subqueries_in_group_by
= False`, with `collapse_group_by` dropping such expressions from the clause.

What the compiler emitted was:

```sql
SELECT COALESCE((correlated subquery), 0) AS c_count, COUNT_BIG(*) AS custdist
FROM customer ORDER BY 2 DESC, 1 DESC
```

— no GROUP BY at all. Here that raises (error 8120). Nothing guarantees it
would: a query that loses its grouping and still parses gets timed and recorded.

Two ways to produce a number were rejected. Emitting the SQL by hand inside
`run_query_orm` is defect C1, the one that invalidated the earlier study. Doing
the outer grouping in Python moves the work out of the database and would report
a Django Q13 time that is mostly a loop over 1.5 million rows.

**It is not a SQL Server quirk.** Oracle refuses the same construct, in its own
words:

    ORA-22818: subquery expressions not allowed here

so two of the four systems in this study forbid a subquery in a GROUP BY
expression and Django's only route to Q13 is closed on both. The two refuse
differently, and the difference matters: Oracle raises, while mssql-django
silently drops the clause and emits a statement with no GROUP BY at all.

Oracle also shows what the alternative costs. `q13_oracle.py` carried its own
copy of the ORM path, and that copy was the *original* Q13 implementation - both
defects the shared module records as fixed, still present, because the override
was never updated when the shared module was corrected. It returned one row
where the query defines forty-five:

    dj_orm   1 row    c_count 11,622,531   custdist 15,500,018
    dj_sql   45 rows  totalling 1,500,000 customers

and those two numbers are exactly ten times the SF1 figures in C3, which makes
the provenance unambiguous. That is the third time in this list a per-vendor
override has shadowed a corrected shared implementation and kept the defect,
after C9 and C16. Both Oracle and SQL Server now import shared implementations
rather than copying them wherever the query is the same.

So the cell is not measured on either system and the run records why. The other
three paths for Q13 run and agree on both. SQLAlchemy's ORM manages it because it can
build a real FROM-subquery via `.subquery()` — a genuine difference in
expressive power between the two ORMs, and a result in its own right rather
than a footnote.

## C18 — SQLAlchemy's row lock silently did nothing on SQL Server

Found by running TPC-C New-Order at concurrency 50, and it is a correctness
defect rather than a performance one.

`sqlalchemy_app/tpcc_queries/t1.py` locked the district row with
`.with_for_update()`, which is the framework's portable spelling and is correct
on PostgreSQL, MySQL and Oracle. Compiled against the mssql dialect it emits
**nothing**: no `FOR UPDATE`, no table hint, no warning, no error.

    postgresql  FROM district WHERE ... FOR UPDATE
    mysql       FROM district WHERE ... FOR UPDATE
    mssql       FROM district WHERE ...

So on SQL Server the row was read unlocked, two concurrent New-Orders took the
same `d_next_o_id`, and both tried to insert an order with it. Measured at
concurrency 50: **522 of 6,778 transactions aborted with IntegrityError, a 7.7%
failure rate.** TPC-C forbids duplicate order ids, so those were not slow
transactions, they were wrong ones.

Django on the same server, through the same intent, emitted the lock:

    FROM [district] WITH (ROWLOCK, UPDLOCK) WHERE ...

and aborted none. It also refuses to compile `select_for_update()` outside a
transaction, raising `TransactionManagementError`, where SQLAlchemy returns a
query that merely does not lock.

**Fixed.** The SQL Server branch uses `.with_hint(District, "WITH (UPDLOCK,
ROWLOCK)")`; the other three dialects keep `.with_for_update()`. Verified by
compilation against each dialect and by re-measurement: the abort rate went from
7.7% to 0.0%, with throughput unchanged at about 6,200-6,600 QPM.

Two things make this worth more than a line in a changelog.

*It is the mirror image of C17.* There, Django's ORM could not express TPC-H
Q13 on SQL Server and failed loudly. Here, SQLAlchemy's ORM could not express a
row lock on SQL Server and failed silently. Neither framework is uniformly more
portable, and the failure modes are not equally safe: a query that will not run
costs a cell, a lock that will not lock costs correctness.

*Only concurrency reveals it.* Every single-threaded measurement of this
transaction - all forty TPC-C latency paths - passes with the lock absent,
because nothing else is competing for the row. The five validation checks would
not catch it either; they compare results, and an unlocked read returns the
right answer when it is alone. It took fifty clients to make the defect visible.

## C19 — Oracle was measuring its result cache, not its queries

The most consequential defect in this list, and the one that came closest to
reaching a published number.

`docker/oracle/init.sql` contained:

```sql
-- Enable result cache (mentioned in paper)
ALTER SYSTEM SET result_cache_mode = FORCE;
```

`FORCE` caches the result set of **every** query and serves a repeat from the
cache without executing it. Oracle's default is `MANUAL`, where the cache is
used only by a query carrying a `/*+ RESULT_CACHE */` hint, and no query in this
study carries one.

The measurement protocol is four repetitions with the first discarded as warmup
and the median of the remaining three kept. Under `FORCE` that means **the
discarded repetition populated the cache and all three timed repetitions read it
back.** Every Oracle timing in the study was a cache lookup.

The size of the error, measured after setting the parameter back:

| | recorded under FORCE | actual, MANUAL |
|---|---:|---:|
| Q03, four consecutive runs | 0.00 s | 32.98, 35.11, 35.37, 37.59 s |
| Q02, first run then repeat | 17.5 s then 0.004 s | — |

Oracle's own `v$result_cache_statistics` reported **Find Count 4,368**: that many
results returned without executing the query.

It also gave Oracle a capability no other system in the study has. PostgreSQL,
MySQL and SQL Server cache *pages*, so a repeated query still executes against
warm buffers. None of them can return a stored result set. Comparing one cached
lookup against three real executions is not a comparison of database systems,
and within Oracle it is not a comparison of ORM against SQL either — both paths
return the same cached rows, so the measured "overhead" was the difference
between two cache lookups.

**Fixed.** `result_cache_mode = MANUAL` in `init.sql`, the cache flushed, and
every Oracle measurement discarded and re-taken. The old rows are kept under
`results/corrected/measurements/superseded/` because the defect is worth being
able to reconstruct, and they are excluded from the results file by the same
non-recursive load that excludes the other superseded set.

Two things make this worth dwelling on.

*The five validation checks cannot see it.* They compare results, and a cached
result is the correct result. `ORM?`, `MATCH`, `SQL=`, `ORM=SQL` and `ROWS>0` all
pass on a query that never ran. Neither does a coefficient of variation: three
cache lookups are extremely consistent with one another, so the run looked more
stable than a real one, not less.

*The comment explains why it was there.* "mentioned in paper" — the parameter was
set because the paper says Oracle's result cache was enabled, which is a
reasonable thing for a paper to say about a production configuration and a
disastrous thing to do to a benchmark that measures repeated identical queries.
It is the clearest case in this list of a setting that is defensible in
isolation and destroys the measurement it sits inside.

## C20 — Django was charged for writing a log SQLAlchemy never wrote

`django_app/settings.py` set `DEBUG = True` and configured the
`django.db.backends` logger at DEBUG with a `FileHandler`. Django therefore
formatted and wrote one line to disk for every statement it executed —
synchronously, inside the timed region. SQLAlchemy has no equivalent
configuration, and the other three settings modules have no `LOGGING` block at
all, so the cost fell on one framework, on one system.

Measured on the same TPC-C New-Order transaction against the same PostgreSQL,
with the handler attached and detached and nothing else changed:

| | median |
|---|---:|
| logging on, as measured | **23.29 ms** |
| logging off | **8.42 ms** |

**14.87 ms per transaction: 63.8% of the recorded time.**

TPC-H is not affected. Measured properly — alternating logged and unlogged runs
so both see the same buffer state — Q06 came out at +0.55%, inside run-to-run
variance. A first attempt suggested 18.8%, but that ran the unlogged case second
against a warmer cache and was measuring the cache, not the logger.

The difference between the two benchmarks is statement count. A TPC-H query
issues one or two statements against seconds of database work, so a log line is
a rounding error. A New-Order issues about twenty against milliseconds. **The
defect is proportional to statements per unit of measured time, which is exactly
why it hid in the benchmark that runs longest and surfaced in the one that runs
shortest.**

Note the direction, because it is not the obvious one. Adding a constant to both
the ORM and the SQL arm moves their ratio *toward* one, so the logging
*understated* Django's measured overhead on PostgreSQL TPC-C. The published
figure was not too harsh on Django; it was too kind.

**Fixed.** `DEBUG = False` — Django also accumulates every executed query in
`connection.queries` when DEBUG is on, which grows without bound across a
campaign — and the logger set to WARNING. PostgreSQL's TPC-C measurements,
latency and throughput, are discarded to `superseded/` and re-taken. TPC-H is
kept.

**How it was found.** Not by any check in the harness. By noticing that
`django_app/logs/benchmark.log` had reached **6.4 GB** while tidying the
repository for review, and asking what was writing it.

**What the re-measurement changed.** All 40 PostgreSQL TPC-C cells were re-taken
with the handler detached. Comparing them against the archived
`superseded/postgresql_tpcc_*.django-sql-logging.csv`, the pooled medians moved:

| | before | after |
|---|---:|---:|
| Django, TPC-C, all systems | +113.6 % | **+115.7 %** |
| SQLAlchemy, TPC-C, all systems | +72.7 % | **+68.1 %** |

Django's overhead went *up* and SQLAlchemy's went *down*, which is the direction
argued above: the logging was inflating both arms of Django's ratio and pulling
it toward one.

The re-run also showed the cost was not confined to Django. SQLAlchemy's paths
sped up too — its indexed T5 SQL baseline by 29.0 %, its T2 by 13.5 % — and
those paths never touched the Django logger. A 6.4 GB file being written
synchronously during a benchmark contends for I/O with everything else on the
machine, so the defect had two components: the work Django did to format and
write each line, which fell on one framework, and the I/O contention that fell
on all four paths. Only the first is visible in the on/off comparison above, and
it was the second that made the absolute times across the whole campaign
unreliable. **A defect measured only on the path that causes it can still be
understated.**

## C21 — the throughput harness leaked a Django connection per worker thread

`scripts/2-benchmark/run_tpcc_throughput.py` spawns a fresh pool of 50 threads
for **every** measured path, and `worker()` never closed the connection each
thread opened. Django's `connections` is thread-local, so nothing else could:
when the thread ended, its server session stayed open until garbage collection
got round to it. Twenty paths per campaign, fifty threads each — roughly a
thousand leaked sessions.

The comment above `dj_orm()` even stated the requirement — *"each worker opens
its own connection on first use and must close it or the pool leaks"* — above a
`finally: pass` that did nothing. The placeholder was written and never filled.

SQLAlchemy was thought structurally immune. Its engine is built once for the
whole run with `pool_size=concurrency+5, max_overflow=10`, so its *connection*
count is bounded by construction no matter how many threads come and go.

**That reasoning was wrong, and C25 records why.** A bounded pool does not
prevent a session leak; it changes how the leak presents. Django's unclosed
connections accumulated at the server until Oracle refused new ones.
SQLAlchemy's unclosed sessions accumulate against a 65-connection ceiling, so
the excess demand *blocks and times out* instead. Both frameworks leak in this
harness. Only one of them was fixed here.

**Why it stayed hidden for three systems.** PostgreSQL, MySQL and SQL Server
have connection limits generous enough to absorb a thousand idle sessions.
Oracle Database Free does not: `processes` defaults to 200. Measured on the
first Oracle indexed campaign, abort rate by path:

| path | aborted | of | rate |
|---|---:|---:|---:|
| django/sql T4 | 4,401 | 7,214 | **61.01 %** |
| django/sql T5 | 7,405 | 41,632 | 17.79 % |
| django/sql T2 | 4,305 | 37,567 | 11.46 % |
| django/orm T3 | 2,127 | 83,353 | 2.55 % |
| **sqlalchemy/sql T2** | 70 | 32,197 | **0.22 %** |

Every failure was `DPY-6005: cannot connect to database`, and the rate climbed
as the campaign progressed — the signature of an accumulating leak rather than
of load. A 280x gap between the two frameworks on the same database, the same
transaction and the same second.

**The damage was not the errors; it was the number beside them.** An aborted
transaction does not commit, so it does not count toward QPM. Django was being
charged for connections the harness failed to close, and the charge appeared as
a lower throughput figure — a harness property presented as a framework
property. This is the same shape as C20 and as limitation 9: a configuration
difference between the two frameworks' *harness code*, not between the
frameworks.

**Fixed.** `worker()` now calls `django.db.connections.close_all()` as its last
act, which closes the calling thread's connections and is harmless on the
SQLAlchemy paths. That alone was not sufficient: sessions still reached 189 of
200, because Django's 50 and SQLAlchemy's bounded pool of up to 65 coexist for
the duration of a run. `processes` was raised to 500 and `sessions` to 800, and
both Oracle schemas were re-measured. **Result: 40 of 40 rows with zero paths
above 1 % aborts.** The 20 contaminated rows are archived to
`measurements/superseded/tpcc_throughput_oracle.django-connection-leak.csv`.

**How it was found.** By porting to a fourth database — the same mechanism as
C6, C7 and C11–C17, and by now the most reliable finder in this list. Three
systems tolerated the defect silently. The fourth had a tighter limit and turned
a leak into a visible 61 % failure rate.

A caution about the first reading: the campaign output was initially misread as
"0.0 QPM everywhere" because a column was parsed by position and `abort_pct` was
taken for `qpm`. The throughput was healthy; the aborts were the real signal.
The defect was found in spite of that misreading, not because of it.

## C22 — the results file's metadata columns were written from constants and a stale log

`scripts/4-analysis/make_all_results.py` fills every row's `dbms_version`,
`orm_version`, `dataset_size_gb`, `campaign_id` and the three `validated_*`
columns. Not one of them was read from the campaign that produced the row.
Found on 2026-08-29 while preparing the paper, by reading the file against
its own logs.

**Versions.** Hardcoded in two tables at the top of the script:

| column | the file said | actually run | where that is recorded |
|---|---|---|---|
| PostgreSQL | 14.9 | **14.23** (Debian 14.23-1.pgdg13+1) | `postgresql_*.campaign.log` |
| MySQL | 8.0.34 | **8.0.46** on localhost; sandbox build never logged | `docs/ENVIRONMENT.md` |
| SQL Server | 2019 Developer | 2019 Developer, **15.0.4480.2 CU32-GDR**, amd64 under emulation | `docs/ENVIRONMENT.md` |
| Django | 4.2.30 | **4.2.0** | `requirements.txt`, `venv/` |
| SQLAlchemy | 2.0.36 | **2.0.23** | `requirements.txt`, `venv/` |

The reviewer of the earlier manuscript asked why the systems were so old; the
answer would have been given with the wrong numbers.

**Provenance.** The `PROVENANCE` map said both PostgreSQL schemas and Oracle
non-indexed were sandbox campaigns, and had no entry for Oracle indexed, which
fell through to the default string `sf10-2026-07`. The campaign logs say
otherwise: `postgresql_indexed.campaign.log` carries this machine's repository
path, port 55432 and the 8-worker parallelism dump that only ever existed here;
all twenty measured Oracle non-indexed queries appear in the group A–G measure
logs written here on 2026-07-31. So 104 PostgreSQL rows and all 108 Oracle rows
— 212 of 432 — carried a wrong or undefined `campaign_id`, and four PostgreSQL
Q11 rows carried a per-row warning about a hardware change between Q11 and the
other queries that did not exist. The sandbox rows for PostgreSQL are the
2-worker runs archived under `measurements/superseded/`. Only MySQL non-indexed
has no local log, and it is the one campaign that stays sandbox.

**Validation.** `load_validation()` read a single file,
`results/corrected/validation.log` — the SF1 PostgreSQL validation of
2026-07-28, three checks, 22/22 pass — keyed by query id alone, and stamped that
verdict on all eight campaigns. Every TPC-H row in the file said `pass`. The
per-campaign logs written since say:

| campaign | validation | in the results file as |
|---|---|---|
| PostgreSQL indexed, Q18 | `QueryCanceled` on the validator's clock | Django −82.4%, SQLAlchemy −12.4%, both `pass` |
| PostgreSQL non-indexed, Q18 | same | Django −36.9%, SQLAlchemy −11.8%, both `pass` |
| PostgreSQL non-indexed, Q13 | same | SQLAlchemy +2.4%, `pass` (Django path timed out in measurement) |
| Oracle non-indexed, Q17 | `DPY-4024` at 300 s | SQLAlchemy +3.6%, `pass` |
| **Oracle non-indexed, Q08** | **`MATCH=DIFF`, `ORM=SQL=DIFF`** — a recorded wrong answer | Django −0.6%, SQLAlchemy −5.0%, both `pass` |
| Oracle indexed, all ten cells | no validation log exists | `pass` |
| MySQL non-indexed | no log survives from the sandbox | `pass` |

Eight cells carry an overhead figure with no passing verdict behind it, and
three more — SQLAlchemy's Q13 on SQL Server (both schemas) and on Oracle — were
never checked at all, because the validator raises on Django's
`Q13NotExpressible` (C17) and stops before comparing the other three paths of
that query. The mechanism is the one this list keeps finding: a column that
looked like a record was a constant.

**Dataset size.** A single `14` for all four systems. The loaded sizes are
21 GB (PostgreSQL, with indexes), ~22 GB (MySQL, with indexes, estimated),
14.4 GB (SQL Server, without) and 10.81 GB (Oracle, without) — not like-for-like
and now stated per system rather than averaged into one wrong number.

**Fixed.** Versions from the campaign logs, `docs/ENVIRONMENT.md` and
`requirements.txt`, qualified per campaign where the sandbox build was not
recorded. Provenance corrected; the Q11 exception removed. Validation read from
every campaign log under `results/corrected/`, keyed (dbms, schema, query), with
two more columns (`ORM=SQL`, `ROWS>0`) and a `validation_source` column naming
the log, so a reader can check the claim. A cell with a timing and no passing
verdict keeps its timing and says so in `status_note`. Cells with no log say
`not_recorded`, which is what they are.

**How it was found.** Not by a check. The venv reported SQLAlchemy 2.0.23 where
the file said 2.0.36; the Q18 note said the sandbox had run out of disk for a
cell whose campaign log showed three clean repetitions on this machine. Two
contradictions between the file and the evidence it claimed to summarise, and
the rest followed from reading the script.

## C23 — every campaign chain measured queries that had failed validation

The rule — validate first, five checks, all must pass before any timing is
kept — is stated in `README.md`, `CLAUDE.md` and the validator's own docstring.
No chain script enforces it. `run_postgres_campaign.sh`,
`run_mysql_campaign.sh`, `run_sqlserver_campaign.sh` and
`run_oracle_campaign.sh` each pipe `validate_queries.py` through `tee` and then
measure every query in their list, whatever the validator printed.
`run_mysql_campaign.sh` even states the intended distinction in a comment —
a query that fails validation only on the clock "is recorded as such rather
than treated as a wrong answer" — and nothing recorded it, because the results
file took its validation columns from an SF1 log (C22).

What the logs show, campaign by campaign:

| campaign | query | validator said | then measured |
|---|---|---|---|
| PostgreSQL indexed | Q18 | `QueryCanceled` (statement timeout) | yes — both frameworks, all four paths |
| PostgreSQL non-indexed | Q13, Q17, Q18, Q20 | statement timeout | yes; Q17 and Q20 then timed out in measurement too, Q13's Django path did, Q18 completed |
| Oracle group C (non-indexed) | Q17 | `DPY-4024` after 300 s | yes; Django ORM timed out at 900 s, SQLAlchemy completed |
| **Oracle group F (non-indexed)** | **Q08** | **`MATCH=DIFF`, `ORM=SQL=DIFF`, `SQL=` ok** | yes — Django −0.6%, SQLAlchemy −5.0% |
| SQL Server both, Oracle group A | Q13 | `Q13NotExpressible` (Django) | yes — Django's cell is a result, not a defect (C17); but the validator stops at that exception, so SQLAlchemy's Q13 (+22.8%, +25.9%, +13.8%) and both baselines on those systems were never compared — three more unverified cells |

Q08 on Oracle is a recorded difference, and C26 diagnoses it: Django's Oracle
module returns four values per row where every other path returns two, which
makes the comparison fail whatever the numbers are. Whether the market-share
values also differ is a separate question C26 leaves open.

Q18 needs saying on its own. Its Django ORM path on PostgreSQL indexed runs in
49.1 s against a 279.0 s baseline — 5.7× faster, the largest "ORM faster" cell
in the study, and until now a headline row in the thesis's table of
configurations where the ORM won. Q18 returns exactly 100 rows by construction
(`LIMIT 100`), so the row count cannot tell a right answer from a wrong one,
and `ORM=SQL` — the check that would — never ran to completion on it. It is a
timing of an unverified statement.

**Decision (2026-08-29).** The eight cells keep their timings. Each carries the
validator's actual verdict in the `validated_*` columns and a `status_note`
saying it was measured without a passing validation; the paper discloses them
as a group; all eight are re-validated when PostgreSQL and Oracle are reloaded,
and any that pass are then unflagged. Q08 on Oracle is additionally a bug to
diagnose in `django_app/queries/q08_oracle.py` before that re-validation.

**Fixed in code (2026-08-29).** `scripts/utils/validated_queries.py` reads a
validation log back and prints the query numbers that passed all five checks;
each of the four chains now loops over that list instead of its own. It fails
closed — a query with no row in the log is not measured, a missing log measures
nothing — and writes what it skipped, with the validator's reason, to the log's
sibling `.gate.log`. `validate_queries.py` exits 1 when any query fails, and
`make_all_results.py` reports a gated cell as `not_run: gated by validation
(C23)` with the verdict. Replayed against the four campaign logs above, the
gate skips exactly the cells this entry lists: Q18 on PostgreSQL indexed;
Q13, Q17, Q18, Q20 on PostgreSQL non-indexed; Q08 in Oracle group F; Q13 on
SQL Server. Nothing in the results file changed — the eleven cells stand by
decision — but the next campaign cannot add to them.

**Also fixed (2026-08-29): the validator no longer abandons a query when one
path raises.** `check()` ran all four access paths inside a single `try`, so the
first exception ended the query and the paths after it never ran. Django cannot
express Q13 on SQL Server or Oracle - a real result, C17 - and that exception
abandoned Q13's whole validation on both systems, leaving SQLAlchemy's ORM and
both hand-written baselines uncompared. Three cells were measured anyway and
recorded as passing. **Reloading the databases would have reproduced the
identical `ERROR` line**, because the fault was in the validator, not the data.

Each path now runs in its own `try`; per-path failures are recorded and printed
by name; every check is computed over the paths that did run. A check whose
inputs are missing reports `n/a`, which is **not** a pass - the gate keeps only
`yes`/`ok`, so an unavailable check still refuses the timing, and
`make_all_results.py` records it as `not_checked` rather than flattening it into
`pass` or `FAIL`. The `ORM=SQL` check now covers **both** frameworks: it
compared Django's pair only, so the mirror of the fault it was added for - one
hitting SQLAlchemy's ORM alone - was equally invisible.

**How it was found.** By comparing the results file's `pass` columns against
the validation tables in the campaign logs, after C22 made the columns suspect.

## C24 — Q16's Django ORM asks a different question than its baseline, and the data hides it

TPC-H Q16 excludes suppliers whose comment matches `'%Customer%Complaints%'` —
one pattern, case-sensitive, the two words in that order. The hand-written
baseline and SQLAlchemy's ORM both write it that way. Django's does not:

```python
# django_app/queries/q16.py
bad_suppliers = Supplier.objects.using(using).filter(
    comment__icontains='Customer'
).filter(
    comment__icontains='Complaints'
)
```

which PostgreSQL receives as

```sql
NOT (ps_suppkey IN (SELECT s_suppkey FROM supplier
     WHERE UPPER(s_comment) LIKE UPPER('%Customer%')
       AND UPPER(s_comment) LIKE UPPER('%Complaints%')))
```

Three differences from the specification, all in the same direction — the ORM's
subquery can select *more* suppliers, so the outer `NOT IN` can exclude more
rows:

| | Baseline | Django ORM |
|---|---|---|
| Patterns | one | two, ANDed |
| Case | sensitive | **insensitive** (`icontains` wraps both sides in `UPPER`) |
| Order | `Customer` must precede `Complaints` | either order matches |

**The results agree anyway.** All eight measured Django cells return 27,840
rows, the same as their baselines, and both `MATCH` and `ORM=SQL` pass wherever
a validation log survives. The two predicates coincide on this dataset because
dbgen inserts the phrase verbatim, in that order and that case — reasoning from
the generator, not re-measured, because no database is currently loaded.

**Which is the point.** Result equality on one generated dataset is not semantic
equivalence, and no check in `validate_queries.py` could have caught this: the
row counts match, the values match, the query is not slow, and nothing errors.
The defect is only visible by reading the statement the ORM emitted against the
statement it was supposed to emit.

**This repository already knew the pattern was wrong.** `q13.py`'s header
documents it in the same words, for the same two-word predicate:

> Its predicate was also wrong: `~Q(comment__icontains='special') &
> ~Q(comment__icontains='requests')` excludes comments containing either word,
> whereas TPC-H excludes comments matching `'%special%requests%'` — the two
> words in that order.

Q13 was fixed to `comment__regex=r'special.*requests'`. `q09.py` carries the
same warning and uses `contains`, not `icontains`. Q16 was never revisited, and
`q09_oracle.py` still has `partkey__name__icontains='green'` where `q09.py` and
`q09_sqlserver.py` have `contains` — the C9 shape again, a per-vendor override
that missed a fix applied to the default.

**Reach.** Q16's Django ORM path, 8 measured cells (four systems x two schemas;
overheads −9.9% to +37.0%). SQLAlchemy's Q16 is correct and unaffected. Q09's
Oracle override is latent: all four Oracle Q09 cells are `not_run` under the
12 GB cap, so it has never contributed a number.

**Fixed 2026-08-30.** The predicate is now a single bound `LIKE`:

```python
bad_suppliers = Supplier.objects.using(using).filter(
    comment__like='%Customer%Complaints%'
).values_list('suppkey', flat=True)
```

`__like` is a registered lookup, not a built-in. `__contains` escapes interior
wildcards, so it can only match one literal run of characters; `__regex` can
express the pattern but mssql-django maps it to `dbo.REGEXP_LIKE`, a
user-defined function the database does not have, and supplying it would make
the ORM path carry a scalar UDF over millions of rows (see `q13_sqlserver.py`).
The lookup keeps the statement ORM-built and passes the pattern as a parameter,
which also sidesteps C14: that rewrite operates on the query text, and Q16 has a
`GROUP BY`.

The lookup was already written inside `q13_sqlserver.py` for the same reason. It
now lives in `django_app/queries/_lookups.py` and both queries import it - two
copies of one lookup is the C9 shape, drifting the moment either is corrected.
`q16_sqlserver.py` imports the ORM path from `q16.py`, so one edit reaches all
four systems.

Verified on the reloaded PostgreSQL: the ORM emits
`s_comment LIKE '%Customer%Complaints%'`, returns 27,840 rows, and Q16 passes all
five checks. **The eight cells still need re-measuring** - the query now asks a
different question than the one that produced their timings - and the three
other systems need the same verification when they are reloaded. The paper
reports Q16's numbers with the divergence stated, and uses the case as its
worked example of what a result-equality check cannot prove.

**How it was found.** By auditing every captured statement for constructs whose
NULL or case behaviour differs between the ORM and the baseline — an audit run
because a reviewer of the earlier manuscript asked whether the differences this
study reports were semantic rather than performance-related. For Q16 the answer
is that one of them is.

## C25 — the throughput harness leaks a SQLAlchemy Session per worker, and C21 declared it immune

`scripts/2-benchmark/run_tpcc_throughput.py` builds one `Session(engine)` per
worker for each of the two SQLAlchemy paths:

```python
def sa_sql(i):
    sess = Session(engine)          # never closed
    def f(rng):
        try:    return sa.run_transaction_sql(sess)
        except Exception:
            sess.rollback(); raise
    return f
```

Nothing closes it. `worker()` calls `django.db.connections.close_all()` as its
last act — the C21 fix — and there is no `sess.close()` anywhere in the file.
Fifty workers times two SQLAlchemy paths times five transactions is 500 sessions
per (system, schema) against a pool of 65.

**The signature.** Exactly **70** transactions abort with

    TimeoutError: QueuePool limit of size 55 overflow 10 reached,
    connection timed out, timeout 30

in seven of the eight `sqlalchemy` / `sql` / T2-Payment rows — and nowhere else
in the 160-row file. Not approximately seventy: seventy, on seven systems whose
throughput spans 37,432 to 125,747 QPM, a factor of 3.4. A pool exhausting
under load would abort in proportion to load. A fixed count across a 3.4x range
is a deterministic effect, not saturation.

The position in the run explains where it lands. Paths execute in the order
django/orm, django/sql, sqlalchemy/orm, sqlalchemy/sql, so **sqlalchemy/sql is
the last path to run** and the only one that meets a pool the preceding
sqlalchemy/orm run has already drawn on. Oracle non-indexed is the one case
with zero aborts; it is also the slowest row in the set, which is consistent
with sessions being returned faster than they are demanded, though that is
inference and was not measured.

**Why C21 missed it.** C21 concluded SQLAlchemy was "structurally immune…
bounded by construction". The bound is real but it is a bound on connections,
not on sessions. Bounding the connections is precisely what converts an
unbounded leak into a queue with a timeout. The defect was visible in the same
output C21 was written from — 70 aborts, in the file, in a column C21 quotes —
and was read as a rounding error.

**What it does to the numbers.** The seven affected rows are SQLAlchemy's T2
Payment *baseline*, which is the denominator of SQLAlchemy's T2 throughput
ratio. Losing transactions to pool contention depresses that denominator and so
inflates the ratio. The direct loss is 70 of ~125,945 attempted (0.056%); the
indirect cost of workers blocked at the pool is **not quantified**, and this
entry does not guess at it.

Recomputing the throughput finding with every T2 row removed:

| System | all five transactions | without T2 | engine threads |
|---|---:|---:|---|
| PostgreSQL | 26.6% | 23.8% | 10 |
| MySQL | 36.1% | 41.5% | 10 |
| Commercial system A | 34.0% | 34.0% | 10 |
| Oracle | 83.6% | 91.5% | 2 — licence cap |

The result the paper draws from this data — that a framework's apparent
throughput cost shrinks on the system whose server saturates first — is
unaffected: the gap between the ten-thread systems and Oracle goes from 2.46x
to **2.69x** when the affected rows are dropped. The conclusion does not depend
on them.

**Fixed 2026-08-30.** Each `sa_orm`/`sa_sql` closure now records its Session on
the returned function as `f._session`, and `worker()` closes it as its last act,
symmetrically with the `connections.close_all()` that C21 added on the Django
side. Returning the session to the pool is what stops the last path to run -
`sqlalchemy/sql`, which meets a pool the `sqlalchemy/orm` run has already drawn
on - from queueing until the checkout times out.

**The eight T2 rows and their Django comparators still need re-running**; the
harness now measures something different. Not yet verified against a live
system: TPC-C throughput needs a loaded database and only PostgreSQL is
resident.

**How it was found.** By being asked why a connection timeout was being treated
as an acceptable measurement. It was not an acceptable measurement, and the
question was the right one: a deterministic constant in an abort column is a
signature, and it had been reported as 0.005% of all transactions — a
denominator that made a structural defect look like noise.

## C26 — Q08's Oracle override returns four columns where every other path returns two

The Oracle validation recorded `MATCH=DIFF` and `ORM=SQL=DIFF` for Q08 while
the two hand-written baselines agreed with each other and both paths returned
2 rows (C23). The cause is a projection, not a number.

`q08.py`, the default, ends its queryset with an explicit projection:

```python
    .annotate(mkt_share=F('brazil_volume') / F('total_volume'))
    .order_by('o_year')
    .values('o_year', 'mkt_share')        # two columns
```

`q08_oracle.py` has no such line, so its rows carry every annotation:
`o_year`, `total_volume`, `brazil_total`, `mkt_share` — **four values**. Its own
`run_query_sql` selects `o_year` and `mkt_share`; so does SQLAlchemy's ORM.

The validator compares rows with

```python
tuple(sorted((norm(x) for x in r.values()), key=repr))
```

— every value in the dict, not a named subset. A four-tuple can never equal a
two-tuple, so `MATCH` and `ORM=SQL` are `DIFF` **whatever the market-share
numbers are**. The verdict was correct; its usual reading — that Django computed
a different answer — is not established.

**What is not resolved.** There is a second structural difference. The default
aggregates with `Sum(Case(...))` after `.values('o_year')`; the Oracle override
annotates a bare `Case` *before* `.values('o_year')` and then sums the
annotation. Django's grouping is sensitive to which annotations exist when
`.values()` narrows the row, and this is the shape `q13.py`'s header documents
as having collapsed a 42-row distribution into one meaningless row. Whether the
Oracle override's grouping is also wrong cannot be settled by reading: it needs
the query run. So this entry establishes that the recorded `DIFF` is fully
explained by the projection, and does **not** claim the values agree.

**Third instance of the C9 shape.** A per-vendor override that missed a fix
applied to the default — after C9 itself (four Django modules carrying Q4's date
window on Oracle) and C24 (`q09_oracle.py` still using `icontains` where the
default and the SQL Server override use `contains`). Every one of them is an
override drifting from a corrected default, and the repository has now produced
three.

**Fixed 2026-08-30.** `.values('o_year', 'mkt_share')` added, matching the
default `q08.py`. The two Oracle Q08 cells must be re-measured before the change
means anything, and the grouping question above is still open: whether annotating
a bare `Case` before `.values('o_year')` rather than summing it after also
changes the grouping cannot be settled by reading, and Oracle is not resident.
Both belong with the reload (plan task B1a).

**How it was found.** By reading the two implementations side by side after the
cell was flagged, rather than by re-running it — which was the point of asking
whether the difference could be diagnosed without a database. It could.

## Two gaps that were not defects but stopped the same campaign

Neither is a wrong answer, so neither gets a C-number, but both had to be closed
before SQL Server could be measured and both have the same cause as C11–C13.

*There was no SQL Server schema.* `data/indexes/sqlserver_indexes.sql` builds
fifteen secondary indexes against tables nothing in the repository creates, and
`scripts/1-setup/load_sqlserver_data.sql` opens by truncating them.
`scripts/1-setup/schema_sqlserver.sql` is the missing half. Its primary keys are
`NONCLUSTERED` on purpose: SQL Server clusters a primary key unless told
otherwise, which would order the table on that key and give the *non-indexed*
configuration an access path PostgreSQL's heap does not have.

*Both existing loaders read files that are no longer produced.*
`load_sqlserver_data.sql` uses `BULK INSERT` from `/tpch-data/*.tbl.clean` and
`setup_sqlserver_data.py` parses the same `.tbl` files, but `data/tpch-raw/` is
empty and gitignored — the pipeline moved to generating the dataset with
DuckDB's `tpch` extension and streaming it in without an intermediate copy.
`scripts/1-setup/load_sqlserver.py` is the streaming loader, matching `load_pg.py`
and `load_mysql.py`.

## How these were found

Not by the statistics. All of them produced stable, reproducible measurements
with low coefficients of variation across repetitions. Nothing errored and
nothing looked anomalous.

C1, C2 and C4 were found by reading the code that produced the numbers. C3 was
found by comparing each Django ORM implementation against its own SQL baseline.
C5 was found by asking why the design grid had holes in it. C6 and C7 were found
by porting to a second DBMS — C7 immediately, because Oracle broke loudly enough
to notice, and C6 only because the empty result it produced on Oracle prompted a
check of what PostgreSQL had returned for the same query. C8 is what all of this
should have caught the first time, and C9 is the first defect it caught by
itself. C11 through C17 were found by porting to a *third* DBMS, which is the
same mechanism as C6 and C7 and by now the clearest pattern in this list: the
defects live in the paths nothing has executed, and the only reliable way to
find them is to execute those paths.

The SQL Server port is the sharpest illustration of it. Seven defects, in code
that had been read and audited more than once, and every one of them appeared
within an hour of the first statement actually reaching a server. Four of the
seven — C14 on three queries, C15, C16 — produced complete, plausible, correctly
shaped, fast results that were answers to different questions: a 46-row
distribution instead of a 45-row one, a profit figure 1.5x too high, an empty
result in 0.74 s. Not one of them would have been visible in a timing, a
coefficient of variation or a plan. They were caught by `SQL=` and `ORM=SQL`,
the two checks added last, each after a defect of exactly this kind had already
reached the results file once.

The general lesson, and the reason `scripts/validate_queries.py` now exists: in
comparative performance work the dangerous errors are not the ones that make an
experiment fail. They are the ones that make it succeed at answering a question
nobody asked.

## C27 — a validation log whose name matched no campaign prefix was skipped in silence

`make_all_results.py`'s `load_validation` reads every verdict the validator ever
wrote and keys it by `(dbms, schema, query)`. It decides which campaign a log
belongs to from the start of its filename, against a fixed table:

    prefixes = (("postgresql_", "postgresql"), ("pg_q11", "postgresql"),
                ("mysql_", "mysql"), ("sqlserver_", "sqlserver"),
                ("oracle_group_", "oracle"))

A file matching none of these was skipped by a bare `continue`.

That table encodes July's naming. `run_oracle_campaign.sh` wrote one log per
query group, `oracle_group_A.validate.log` through `oracle_group_G`, so
`oracle_group_` was the only Oracle spelling that had ever existed. The other
three systems were validated per schema and their logs are named for it -
`sqlserver_non_indexed.b1a.validate.log`, `postgresql_indexed.b1a.validate.log`.

The B1a re-validations of 2026-08-30 ran per schema on Oracle too, and were named
to match the convention the other three use: `oracle_non_indexed.b1a.validate.log`,
`oracle_non_indexed.q08.b1a.validate.log`, `oracle_non_indexed.q17.b1a.validate.log`,
`oracle_indexed.b1a.validate.log`. None of them starts with `oracle_group_`. All
four were discarded.

Nothing said so. `make_all_results.py` printed its usual "432 rows" summary and
exited zero. Four Oracle cells kept citing a July verdict that the August run had
superseded, and one of those verdicts was wrong in a way that mattered: Q08's
`MATCH=FAIL:DIFF ORM=SQL=FAIL:DIFF`, which had been read as Django computing a
different answer, and which C26 had just shown to be a projection shape. The
re-validation that cleared it existed on disk, in the right directory, in the
right format, and was ignored.

The failure is the silence, not the table. A table of known prefixes is a
reasonable design; a `continue` that discards a file the pipeline was built to
read is not. So both are fixed:

  * The two per-schema Oracle spellings are accepted alongside `oracle_group_`.
    A bare `oracle_` would have been shorter and would also have swept in
    `oracle_chain.log` and `oracle_reload_G3.log`, which are shell transcripts
    that happen to contain a `tee` of a validator table.
  * A file named `*.validate.log` is a validator artifact by its name, so one
    that matches no prefix is a naming mistake rather than an unrelated file. It
    is now collected and reported on stderr, naming each path, with the
    consequence stated: any verdict in it is not in the results file. Logs that
    legitimately match nothing - `tpcc_*`, `*_load.log`, `*_chain.log`, the SF1
    `validation.log` - do not end in `.validate.log` and stay quiet.

Verified by copying a valid log to `oops_typo.validate.log` and rebuilding: the
warning names it. Removing it silences the warning again.

C22 was the same shape - a verdict attributed to a campaign that did not produce
it - and was found because the numbers looked wrong. This one produced no wrong
number anywhere. It withheld a correct verdict from four cells and reported
success, which is the harder failure to notice and the reason the guard is
mechanical rather than a note in the workflow.

## C28 — Django and SQLAlchemy quote the TPC-C ORDER table into two different Oracle tables

`ORDER` is reserved in all four dialects, so both frameworks must quote it. In
Oracle, quoting is also what makes an identifier case-sensitive, and the two
frameworks quote the same declared name into two different tables:

    Django      db_table='order'        -> quote_name uppercases  -> "ORDER"
    SQLAlchemy  __tablename__='order'   -> quoted as declared     -> "order"

`create_tpcc_schema_oracle.sql` creates `"ORDER"`, and `load_tpcc.py`'s `quoted()`
writes 300,000 rows into it. So Django works and SQLAlchemy's ORM cannot see the
table at all:

    ORA-00942: table or view "TPCC"."order" does not exist
    T1 sqlalchemy/orm: 0.0 QPM, 0 committed, 33,014 aborted (100.0%)

The unresolved part is that July's campaign recorded this same path at 11,549.8
QPM with zero aborts, and `git show fd42265` - the commit that reported it - has
byte-identical `quoted()` and schema file. One table cannot answer to both
spellings, so July's database held something the repository does not describe.
What, is not recoverable from here: no log records the schema creation, and the
container is long gone. The Oracle build also differs (C22a: the image tag
`23-slim` yielded 23ai then and 26ai now), but identifier quoting is client-side
and version-independent, so the version does not explain it.

Fixed with a synonym, appended to the schema file so it travels with the schema:

    CREATE OR REPLACE SYNONYM "order" FOR "ORDER";

Oracle resolves a synonym once at parse time and DML through it reaches the table
directly, so it costs nothing per row and cannot advantage either framework. The
alternative - a per-vendor table name in one or both model files - would have put
an Oracle quoting quirk into models shared by four systems. Both paths verified
after the change: SQLAlchemy's T1 ORM completes, Django's is undisturbed.

This is a reproducibility failure of exactly the kind the study exists to catch.
It was found by reloading from the committed scripts and discovering that they do
not produce the database the recorded numbers came from.

## C29 — Oracle's process limit refused connections, and the refusals were charged to Django

With C28 fixed, the throughput run still aborted, on a different path: Django's
hand-written SQL, at 7.4% on T2, 0.7% on T3 and 35.1% on T5 indexed, and similar
non-indexed. The error is not a transaction failure:

    DPY-6005: cannot connect to database

and the listener log carried 1,466 instances of TNS-12516, which is the listener
declining a connection because no service handler is free. The instance was full:

    processes limit                                200
    Oracle background processes, measured at idle   82
    SQLAlchemy pool (pool_size 55 + overflow 10)    65
    Django workers                                  50
                                                   ---
                                                   197

Three processes of headroom, and any spike exceeds it. The SQLAlchemy engine is
built once for the whole run and its pool stays open while Django's paths
execute, so Django connects last, into a nearly-full instance, and takes every
refusal. Neither framework is at fault and the effect is not symmetric: it is
charged to whichever framework runs second, as a lower QPM.

The harness already carries a comment describing this shape - `django/sql T2
11.46%, T3 9.17%, T5 17.79%, T4 61.01%` on the Oracle indexed campaign - which
was diagnosed as the harness leaking one Django connection per thread and fixed
by calling `connections.close_all()` in `worker()`. That fix is correct and is
still needed. It was not the whole cause. A per-thread leak and a process ceiling
produce the same symptom on the same paths, and the first was found and the
second was not, because after the fix the run happened to fit.

Fixed at the instance, not in the harness:

    alter system set processes=600 scope=spfile;
    alter system set sessions=1000 scope=spfile;

A server-side limit applies equally to both frameworks, so raising it removes an
artefact rather than favouring anything. Re-run after the change: 40 rows, zero
aborts, zero DPY-6005.

Recorded here because the number that matters is not the abort rate. It is that
Oracle's TPC-C throughput at 50 clients was, in July, measured against an
instance whose connection ceiling the workload was already touching, and nothing
in the results file said so.

## C30 — a campaign was attributed to a second machine on the strength of a missing log

`make_all_results.py` tagged MySQL's 44 non-indexed cells with
`campaign_id = sf10-2026-07-sandbox`, and `docs/ENVIRONMENT.md` described that
sandbox in detail: a cloud container, roughly 24 GB of disk, one database
resident at a time. `LIMITATIONS.md` carried it as limitation 5, "two campaigns
come from a retired machine". The paper carried it as a threat to validity, and
`phase_b.py` carried a sensitivity arm that recomputed every headline figure
"without the sandbox campaign".

None of it was established. The comment in `PROVENANCE` states the whole
argument:

> Only MySQL non-indexed has no local log, and it is the one campaign that stays
> SANDBOX.

That is an inference from an absence. No log survives for that campaign, and the
conclusion drawn was that it therefore ran somewhere else. The alternative
explanation — that the log was simply not kept — was never excluded, and it is
the likelier one, because the campaign predates the logging discipline the later
campaigns follow.

The author ran every campaign and states that every measurement in this study was
taken on the one Apple M4. Testimony from the person at the keyboard outranks an
inference from a missing file, and nothing in the repository contradicts it.

What was wrong, and what it cost:

  * 44 rows carried a false `campaign_id`, and 108 rows carried text about a
    sandbox in their notes or version columns.
  * `CROSS_MACHINE` attached a warning to every MySQL row saying its
    indexed-against-non-indexed comparison "includes a hardware change". It does
    not. That warning discouraged a comparison the data supports.
  * The paper's threats section disclosed a limitation that does not exist, and
    the sensitivity table tested removal of a group defined by a machine that was
    never used.
  * The Q16 re-measurement was written up as crossing machines as well as code,
    which made a clean result look dirty.

Fixed by removing the SANDBOX constant, pointing MySQL non-indexed at LOCALHOST,
emptying `CROSS_MACHINE`, and renaming the version qualifier from "sandbox venv
not recorded" to "venv not logged for this campaign".

The sensitivity arm is kept and relabelled rather than deleted. The group is
still worth testing — MySQL non-indexed is the one campaign with no surviving
log, so its server build is unrecorded and its cells cannot be audited the way
the others can — but the arm now selects on the campaign rather than on a
machine. Removing it moves Django's pooled TPC-H median from 0.93% to 1.03%.

The general lesson is C22's, one turn further. C22 was metadata written from
constants rather than from the system. This is metadata written from an
inference, which is worse, because a constant is obviously unverified while an
inference reads like a finding. "No log survives" and "it ran elsewhere" are
different statements, and only the first one was ever true.

## C31 — the MySQL driver is not in the dependency list, and the shim that supplies it expires at Django 6.0

Both frameworks reach MySQL through PyMySQL. Django reaches it through a shim
installed at package import, before any settings module is read:

    django_app/__init__.py
    import pymysql
    pymysql.install_as_MySQLdb()

and SQLAlchemy through the DSN, in `sqlalchemy_app/database.py` and in every
MySQL campaign script:

    mysql+pymysql://{user}:{password}@{host}:{port}/{database}

So the two frameworks are on the same driver, and no MySQL measurement in
`results/all_results.csv` is wrong because of this. What is wrong is that
nothing in the repository says so, and that the arrangement stops working at
the next Django version this study wants to use.

**The driver is undeclared, and the declared one is wrong.** `requirements.txt`
pinned `mysql-connector-python==8.2.0`, which no module in the repository
imports. It did not name PyMySQL at all. `docs/guides/REPRODUCIBILITY.md` tells
a reader to expect `mysqlclient`. `mysqlclient` 2.2.8 *is* installed — and is
imported by nothing, because while `install_as_MySQLdb()` is in effect
`import MySQLdb` resolves to PyMySQL and the compiled driver sitting in the
venv is inert. The MySQL rows of the results file were therefore produced by a
driver the dependency list does not name and the reproduction guide names
incorrectly. This is C22 at one remove: not metadata written from a constant,
but metadata contradicted by the environment it claims to describe.

**The shim clears Django's floor by three patch versions, on a comparison that
is not about PyMySQL at all.** Django's MySQL backend gates on the DBAPI's
reported version:

    venv/lib/python3.11/site-packages/django/db/backends/mysql/base.py:33
    version = Database.version_info
    if version < (1, 4, 3):
        raise ImproperlyConfigured(
            "mysqlclient 1.4.3 or newer is required; you have %s." % ...
        )

pip reports the installed distribution as `PyMySQL==1.1.2`, but the module
reports a MySQLdb-compatible identity:

    pymysql.__version__      1.4.6
    MySQLdb.version_info     (1, 4, 6, 'final', 1)

which clears `(1, 4, 3)` by three patch releases of a version number that
belongs to a different project. Django 5.2 keeps that floor. Django 6.0 raises
it to `(2, 2, 1)`, and the shim fails at import:

    ImproperlyConfigured: mysqlclient 2.2.1 or newer is required; you have 1.4.6

A Django upgrade past 5.2 therefore removes the MySQL column of the grid
entirely. It does so at import, before a query runs, which is the good case —
the failure is loud.

**The obvious repair introduces the one defect this study is least able to
absorb.** Moving Django to `mysqlclient` while leaving SQLAlchemy on
`mysql+pymysql://` would put a C extension under one framework and a pure-Python
driver under the other, on the row whose entire purpose is to compare the two
frameworks' client-side cost. Row fetching and type conversion — the work the
ORM overhead figure is largely made of — would then differ by implementation
language, and the difference would be charged to the framework. That is C20's
shape (Django billed for work SQLAlchemy never did) and C29's (the cost landing
on whichever framework ran second): every MySQL ORM/SQL ratio moves, in the
same direction, for a reason that has nothing to do with either ORM. **Both
frameworks move together or neither moves** — `mysqlclient` under Django and
`mysql+mysqldb://` under SQLAlchemy — and the driver name and version are
recorded per framework on every raw row so the parity is checkable rather than
asserted. Frozen as a gate in `SF1_RERUN_PLAN.md` G2 and §5.

**Found alongside it, in the same file.** `pandas` and `seaborn` are declared
and are not installed, while ten modules under `scripts/3-moef` and
`scripts/4-analysis` import them. `jupyter==1.0.0` is pinned; the repository
contains no notebook and no import of it. `duckdb` 1.5.5 generates the TPC-H
data for six modules under `scripts/1-setup` and was pinned nowhere. Three
entries were ranges — `oracledb>=2.0.0` against an installed 3.4.1,
`mssql-django>=1.3` against 1.6, `pyodbc>=5.0.1` against 5.3.0 — so a
reproduction attempt got whatever the index served that day, which is the
opposite of what a pin is for.

What is *not* claimed here: whether pandas was installed during the SF10
campaigns and later removed is not recorded anywhere, and nothing is concluded
from its absence. C30's lesson applies directly. "pandas is not installed
today" and "the analysis ran without pandas" are different statements, and only
the first one is true. The loaders under `scripts/1-setup` use duckdb rather
than pandas and run as they stand, and `make_all_results.py` is stdlib-only, so
the results file regenerates either way.

Fixed by rewriting `requirements.txt` with exact `==` pins, one driver per DBMS
named together with the framework that uses it, and the absent-but-required
packages flagged in place rather than quietly dropped; by adding
`requirements-lock.txt`, a `pip freeze` of the transitive set with the
interpreter version and platform in its header; and by removing
`mysql-connector-python` and `jupyter`, which were dependency-list fiction.

The lesson is that a package pinned but never imported and a package imported
but never pinned are the same defect seen from two sides, and neither one fails
a test run. The harness worked throughout, because the environment on the
machine was right and only the file describing it was wrong. `validate_queries.py`
checks the queries; nothing was checking the environment.

## C32 — the validator's statement ceiling does not survive a timeout, and it fails on one framework only

`scripts/validate_queries.py` bounds every statement so that a query the
physical design cannot support cannot block a campaign indefinitely. The
comment above `TIMEOUT_S` says exactly why it exists:

> Q17's correlated subquery ran for over half an hour on Oracle without the
> LINEITEM part-key index and would have blocked the campaign indefinitely.
> Bound it.

On PostgreSQL the ceiling is `SET statement_timeout`, applied once per query
check to the Django connection and to the SQLAlchemy session. `statement_timeout`
is session-scoped, and a SQLAlchemy `Session` does not keep it across the
rollback that a timed-out statement forces. Five lines reproduce it:

    s.execute(text("SET statement_timeout = 2000"))
    s.execute(text("SHOW statement_timeout"))     -> '2s'
    s.execute(text("SELECT pg_sleep(5)"))         -> OperationalError
    s.rollback()
    s.execute(text("SHOW statement_timeout"))     -> '0'

The mechanism is PostgreSQL's documented treatment of `SET`, not anything about
pooling: a `SET` executed inside a transaction that is later aborted is undone
when the transaction rolls back. `arm_timeout` issues the `SET` on a `Session`
that is holding an open transaction, the timed-out statement aborts it, and the
`sess.rollback()` on the next line — which `check()` performs deliberately, so a
failed statement does not leave the session unusable — takes the ceiling with
it. Three variants, measured:

    SET inside the session's transaction, then rollback   ->  0
    SET then commit(), then rollback                      ->  2s
    libpq connection option, then rollback                ->  2s

That is also why the asymmetry falls the way it does. Django's connection runs
in autocommit, so its `SET` is committed the moment it is issued and survives
its own path timing out. SQLAlchemy's does not. Neither framework is at fault;
the harness set one ceiling in a durable place and the other in a place a
rollback reaches.

Observed in the SF1 compatibility run (PostgreSQL 18.6, Django 6.0.8,
SQLAlchemy 2.0.52, non-indexed, `VALIDATE_TIMEOUT=600`). Q17's four paths, in
execution order, by how long each ran:

    Django SQL          594 s   cut at the ceiling
    Django ORM          586 s   cut at the ceiling
    SQLAlchemy ORM      584 s   cut at the ceiling
    SQLAlchemy SQL      790 s   RAN UNBOUNDED — the ceiling was already gone

Two backends were open at the time, and `pg_stat_activity` shows the shape
plainly: the Django backend idle, its last statement literally
`SET statement_timeout = 600000`, and a second backend 691 seconds into a
statement it should have abandoned at 600. Q20 repeated it.

The bug is not that a query is slow. It is that **the ceiling is
framework-asymmetric**: the Django paths are bounded and the SQLAlchemy paths
are not, so the two frameworks are validated under different rules, and it is
the second SQLAlchemy path in each check that escapes. That is the shape of C20,
C29 and C31 — a difference in the machinery charged to the framework — and here
it lands on the mechanism that decides whether a cell is trustworthy at all.

It also undermines the censoring rule the SF1 rerun depends on
(`SF1_RERUN_PLAN.md` §5). That rule classifies a timed-out ORM run as
`ORM/SQL > 60` rather than as a missing value or a ceiling-valued observation.
A path that runs unbounded produces neither a clean timing nor a clean censor:
it produces a number that looks measured, taken under no ceiling, next to three
that were taken under one.

Fixed by setting the ceiling where no transaction can reach it. On PostgreSQL
that is a libpq connection option rather than a SQL statement, so it is the
session default from the moment the backend starts:

    create_engine(dsn, connect_args={"options": "-c statement_timeout=600000"})

For the vendors whose ceiling is a driver attribute rather than a server
setting — Oracle's `call_timeout`, pyodbc's `timeout` — it is applied in a
`connect` event so that every connection the pool ever opens carries it, not
just the first. MySQL's `SET SESSION max_execution_time` is not transactional
and was never at risk, but it moves to the same event for one rule everywhere.

And because this was invisible until someone ran `SHOW` by hand, the effective
ceiling is now read back off the server and asserted before each SQLAlchemy
path is timed. A ceiling that is set and assumed is how this got here.

The lesson is the one C19 taught about Oracle's result cache: a setting the
harness issues is not a setting the database is under. C19 asserted
`result_cache_mode` before each campaign for exactly this reason. Every other
session-scoped setting the harness depends on deserves the same treatment, and
this one guards the boundary between a measurement and a stall.

---

## C33 — the pilot gate counted a partially censored cell as a broken design

PostgreSQL non-indexed Q13 is one cell in which three of the four paths
complete and the fourth does not. Django's ORM formulation exceeded the 900 s
ceiling in the cell warmup; `django/sql`, `sqlalchemy/sql` and `sqlalchemy/orm`
all finished in about a second. `run_block.py` did the right thing with it: a
path that exceeds the ceiling in warmup is excluded from all eight blocks and
recorded once as a one-sided bound, rather than spending 8 x 900 s re-proving
what the warmup already established.

`pilot_gate.py` then failed the run. Its design-integrity check required every
cell to hold eight blocks of four paths, so a cell of eight blocks of three
read as evidence that the counterbalancing had not happened:

    FAIL  every cell has 8 blocks x 4 paths   Q13: 8 blocks

The consequence is not cosmetic. Section 8.5 says that a gate failure excludes
every measurement in the run from the campaign, so a correctly recorded
censoring would have discarded a four-hour campaign of 600 good executions.
Nothing in the data was wrong; the check did not know about a case section 6 of
the analysis plan describes explicitly.

The check now derives each cell's expected width from the data instead of
assuming it: four paths, less any path with a `timeout` at `is_warmup = 1`.

The second half of the defect is worse and was found while fixing the first.
The check was keyed off the measured rows alone, so a cell whose *four* paths
all exceeded the ceiling — Q17, Q20 and Q21 on this same run — contributed no
rows and was therefore never checked, never counted and never mentioned. The
gate said nothing about three entire queries. It is now keyed off every row, a
fully censored cell is asserted to carry no measured rows, and the censoring is
printed:

    ok    every cell has 8 blocks x 4 paths, less any censored in warmup
          4 cell(s) censored in warmup   Q13 (django/orm); Q17; Q20; Q21

This is the same failure shape as C27, where a validation log whose name
matched no campaign prefix was skipped in silence. A check that can only see
the rows that exist cannot report the rows that do not, and absence is exactly
what censoring produces. The rule the repository already had — absence is never
silent, and a blank cell is a bug — has to hold for the checkers too, not only
for the results file.

---

## C34 — the analysis could not read the measurements it was given

`make_all_results.py` has never been able to consume a `run_block.py` file.

The two writers produce different shapes. `run_query.py` emits one row per
(query, framework, path) with a `median_s` column already aggregated;
`run_block.py` emits one row per *execution* — eight blocks times four paths,
plus warmups — with `elapsed_s` and no median at all. `load_measurements` keyed
rows by `(dbms, schema, query_id, framework, path)` and assigned `m[key] = r`,
so reading a block file the last row for a path simply won. That row might be a
block warmup, a censored execution, or a failure; whichever it was, it carried
no `median_s`, and the builder's

    sql_t = f(sql, "median_s") if sql and sql.get("status") == "ok" else None

left every cell without a time. The summary read

    432 rows = 4 DBMS x 2 frameworks x 2 schemas x 27 queries
      0 complete   (both paths measured, overhead computed)

for four completed SF1 campaigns — PostgreSQL and MySQL, both configurations,
2,632 measured executions — sitting in the directory it was reading.

Nothing announced it. The builder emitted its 432 rows as designed, each with a
`status_note` explaining an absence, and the absence was its own doing. The rule
this repository already had, that absence is never silent, held for the
measurement files and not for the step that reads them.

It now detects a block file by its `block` and `is_warmup` columns and
aggregates: `median_s` over the measured blocks of each path, a status derived
from the declared outcomes (`ok`, then `not_expressible`, then `timeout`, then
`error`), and the number of blocks that contributed.

The second half of the fix matters more than the first. The overhead column was
computed as `median(orm) / median(sql)` — a ratio of medians. The estimand
ANALYSIS_PLAN section 1 defines is the median of the within-block paired log
ratios, formed where both arms saw the same substitution parameters and ran
adjacent in time. Those are different quantities, and the second is the entire
reason the block design exists. Aggregating each path to a median first and
dividing afterwards discards the pairing at the last step, after the whole
protocol was built to create it. The aggregation now carries `paired_ratio` per
(cell, framework) and the builder prefers it, falling back to the ratio of
medians only for `run_query.py` files, which have no pairing to preserve.

Checked against `pilot_gate.py`, which computes the estimand independently:
PostgreSQL indexed Q15 reads `overhead_ratio` 1.9266 against the gate's +92.7%,
and SQLAlchemy 1.0026 against +0.3%.

## C35 — TPC-C rows carried no scale factor, so no build but SF10 could see them

`run_tpcc.py` and `run_tpcc_throughput.py` never wrote a `scale_factor` column.
`_row_is_this_scale` accepts a blank scale factor only when building SF10 —
correctly, because the SF10 measurement files predate the column and for them
blank means ten, while for any other campaign a blank is a row whose provenance
cannot be established.

The consequence was that every TPC-C row was excluded from the SF1 build. All
eight TPC-C configurations reported `0 complete, 10 not_run` while their
measurements sat in the same directory as the TPC-H ones, and the note against
each cell gave a standing reason for the system rather than saying the rows had
been filtered out.

Both writers now record it. For the files already written, a *missing* column is
now distinguished from a *blank* one: a file with no `scale_factor` column at all
takes its provenance from the scale-specific directory it lives in, which is
exactly the separation `results_paths.py` exists to enforce. A file that has the
column and leaves it empty is still a row that cannot be placed, and is still
excluded.

## C36 — Oracle had no branch in the TPC-C campaign script

`run_tpcc_campaign.sh` selects per-vendor settings in a `case` with arms for
PostgreSQL, MySQL and SQL Server, and a default of

    *) echo "unknown dbms: $DBMS" >&2; exit 2 ;;

Oracle fell through it. The script that measures TPC-C could not measure Oracle
at all, which means the study's four-system TPC-C claim was reachable on three.
The Oracle TPC-C numbers in the SF10 results came from the chain scripts, not
from this path, and this script was the one the plan documents.

Added, reading the same environment variables as every other arm. Oracle then
ran all five transactions on all four paths at the first attempt.

## C37 — --resume could never be satisfied, so it duplicated instead of resuming

`already_done` in `run_block.py` decided a cell was complete with

    return len({(r["block"], r["path"]) for r in rows}) >= 8 * 4

`path` is `sql` or `orm`; the framework is a separate column. The set could
therefore hold at most 8 x 2 = 16 distinct pairs and the test demanded 32. No
cell was ever considered done. Every `--resume` re-ran every query it was given
and appended a second copy of the rows, which the gate reports as a cell with
eight rows per block instead of four — a broken design, in a file whose design
was fine.

It surfaced when the SF0.01 PostgreSQL run was interrupted and restarted: 1,216
measured rows where the other three engines had 696.

The key is now `(block, framework, path)`. Every committed SF1 measurement file
was audited for duplicates and none carries any, because each campaign happened
to run start to finish in a single invocation.

## C38 — Oracle's statistics have never been gathered, in any campaign

`manage_indexes.py` gathered Oracle statistics with

    cursor.execute(f"BEGIN DBMS_STATS.GATHER_TABLE_STATS(USER, '{table}'); END;")

Django's Oracle backend strips a trailing semicolon from every statement, so
what reached the server was `BEGIN ...; END` and it failed to compile:

    ORA-06550: PLS-00103: Encountered the symbol "end-of-file"

The call sat inside a `try` whose `except` printed `⚠ Warning: Could not update
statistics` and continued. Every Oracle campaign in this study, SF10 included,
therefore ran against whatever statistics happened to exist — which for a
freshly loaded schema with no gather is none, leaving the optimiser on defaults.

This is the same defect as the SQL Server statistics gap that cost a campaign,
with a different cause and a worse reach, and it had been present far longer.
`cursor.callproc` now issues it, and `run_pilot.sh` gates on the rebuild
succeeding rather than warning and proceeding.

## C39 — two schema files chose their own database, and one emptied a loaded one

`schema_sqlserver.sql` began with `USE tpch;` followed by eight
`DROP TABLE IF EXISTS` statements. Applying it to a different database with
`sqlcmd -d tpch_tiny` silently switched back and dropped all eight tables of the
loaded SF1 database. `schema_mysql.sql` opened with
`DROP DATABASE IF EXISTS tpch;` and was stopped only by the loading role
lacking the privilege to execute it.

A file that selects its own database cannot be aimed, and every caller that
believes it is aiming one is wrong without being told. Both now take the
database from the connection alone.

The recovery was a reload from `tpch1.duckdb`; no measurement was lost, because
those campaigns had already been superseded. The audit that should have preceded
it is now part of the setup: every schema file is checked for `USE`,
`CREATE DATABASE`, `DROP DATABASE` and `ALTER SESSION SET CURRENT_SCHEMA` before
it is applied to anything.

---

## C40 — Oracle's Q22 averaged over the wrong population on seven of eight sets

`django_app/queries/q22_oracle.py` computes the account-balance threshold that
Q22's outer query filters on. The outer filter used the parameter set:

    .filter(cntrycode__in=country_codes, acctbal__gt=avg_acctbal, ...)

while the average it compares against named the codes as literals:

    Q(phone__startswith='13') | Q(phone__startswith='31') |
    Q(phone__startswith='23') | Q(phone__startswith='29') |
    Q(phone__startswith='30') | Q(phone__startswith='18') |
    Q(phone__startswith='17')

Those seven are exactly set 0's country codes. So on set 0 the average was taken
over the right customers and the module agreed with everything; on the other
seven sets it averaged over set 0's population, produced a threshold belonging to
a different query, and returned different rows. Validation caught it as
`MATCH=DIFF` against SQLAlchemy's ORM and `ORM=SQL=DIFF` against its own
baseline, on seven of eight sets, while set 0 read `ok` across the board.

This is the fifth instance of one shape — Q01, Q03 and Q06 in Django's ORM and
Q16 in SQLAlchemy's were the first four — and it is the shape that a byte
identity check cannot see, because the hardcoded value *is* the value set 0
carries. Only running every parameter set exposes it. That is why
`validate_queries.py` grew `--sets=all`, and it is why the pre-campaign
validation runs with it rather than with the default of set 0.

It is also the fourth defect found in a per-vendor override module, after C9's
four date-literal branches and C26's Oracle Q08. A vendor override is written by
copying the default module and changing what the vendor needs; what does not get
changed is what nobody looks at again. Every per-vendor module now has to pass
all eight sets before a campaign, on the vendor it overrides.

The average is now built from `country_codes`, the same list the outer filter
uses, so the two cannot diverge:

    code_filter = Q()
    for code in country_codes:
        code_filter |= Q(phone__startswith=code)

Re-validated on Oracle at SF1: 8/8 sets pass all five checks.

---

## C41 — TPC-C ran against the TPC-H database, and reported success

Two defects, one of which hid the other.

`run_tpcc_campaign.sh` selected its database with `${POSTGRES_DB:-tpcc}` and the
three equivalents. That reads as "tpcc unless told otherwise", but
`campaign-env.sh` exports `POSTGRES_DB`, `MYSQL_DB`, `SQLSERVER_DB`,
`ORACLE_USER` and `SA_DSN` pointing at the *TPC-H* database, because that is what
the TPC-H campaign needs. So an inherited `tpch` won, and the TPC-C campaign ran
all five transactions against the TPC-H schema. Every one of the twenty paths
failed with

    relation "warehouse" does not exist

The variables were made overridable deliberately, to stop the container's
hardcoded credentials overriding a correct environment. That was right; sharing
one variable name between two benchmarks was not. The TPC-C target now comes
from `TPCC_POSTGRES_DB`, `TPCC_MYSQL_DB`, `TPCC_SQLSERVER_DB`,
`TPCC_ORACLE_USER` and `TPCC_SA_DSN`, each defaulting to the TPC-C database, so
a TPC-H environment cannot reach it.

The second defect is the serious one. With all twenty paths failing, the script
printed

    ############ TPC-C postgresql indexed finished ############

and exited 0. The chain above it would have moved on to the next configuration
and then the next system, leaving an empty TPC-C column behind a line that says
"finished". It was caught only because the throughput harness, which does its
own cardinality check against `tpcc_config`, raised on the same missing table
and stopped the run.

This is the shape of C34 again: a step that reports absence it caused itself. A
campaign that measures nothing must not be distinguishable from a campaign that
measured nothing only by reading the file afterwards. TPC-C is five
transactions times four paths, so the script now asserts 20 of 20 rows with
status `ok`, prints the count in its own completion line, and exits non-zero
otherwise.

`run_system.sh` invokes the throughput harness directly rather than through the
campaign script, so it built the same TPC-C environment for that step, and
restores the TPC-H target before the next configuration's campaign - the two
benchmarks alternate within one system and neither may leak into the other.

Verified by running the campaign with `POSTGRES_DB=tpch` deliberately exported:
20/20 paths ok.

---

## C42 — a client-side ceiling was recorded as a word, so the gate scored a default

`run_block.py` reads the statement ceiling back off the server before timing
anything (C32). PostgreSQL and MySQL answer with a duration; Oracle and SQL
Server bound the client round trip instead, and for those the harness recorded
the literal string

    client-side

`pilot_gate.py` could not parse that, returned None, and fell back to its
`DEFAULT_CEILING_S` of 900 s. SQL Server's indexed campaign was deliberately run
at 2700 s — the retry ceiling ANALYSIS_PLAN.md section 8.3 declares, needed
because Q18's Django ORM path takes about 345 s and 900 s would leave less than
the required 5x margin. The gate scored it against 900 s anyway and failed
section 8.3 at 4x. Against the ceiling actually in force the same run passes at
12x.

The value was never unknown: the harness is the thing enforcing it. It now
records `client-side:2700`, and the gate parses that. A bound the harness
applies and does not write down is a bound the analysis cannot check, which is
the same lesson as C32 one level further out.

---

## Disclosure — SQL Server indexed fails section 8.1, and why it is kept

This is not a correction. It is a result that fails a pre-registered bound, and
the decision was to report it rather than to change the bound.

    SECTION 8.1  NOISE   (median CV <= 5.0%, p90 <= 15.0%, share > 25.0% <= 5.0%)
      ok    median CV  2.76%   bound 5.0%
      FAIL  p90 CV    23.50%   bound 15.0%
      FAIL  share above 25.0%:  8.4%   bound 5.0%
            noisiest: Q17 sqlalchemy/orm   CV 85.30%

Section 8.1 computes each path's coefficient of variation across the eight
blocks, and every block draws its own substitution parameters. For a query whose
runtime genuinely depends on those parameters, the statistic measures parameter
sensitivity and not measurement noise. Section 2.1 already concedes this for
Q18, which is excluded from the CV distribution for exactly that reason.

Two pieces of evidence say that is what this is.

Dividing each execution by its own block's median across the four paths removes
the per-block parameter effect and leaves path-specific variation:

    campaign                as 8.1 measures it        block effect removed
    PostgreSQL indexed      median 1.53%  p90  4.07%  median 0.27%  p90  0.60%
    MySQL indexed           median 1.74%  p90  4.53%  median 0.17%  p90  0.66%
    SQL Server indexed      median 2.76%  p90 23.50%  median 2.30%  p90 14.70%

Almost all of the spread on every engine is parameter effect, and SQL Server's
p90 falls below the 15% bound once it is removed.

And the pattern is reproducible. Re-running Q17 and Q09 on the same host after
the campaign put the slow executions in the same blocks: Q17's sqlalchemy/orm
path is slow in blocks 4, 5, 7 and 8 in both runs. A measurement that reproduces
block for block is repeatable; what it is not is constant across parameter sets.

What remains after all that is a real finding rather than an artefact. In Q17,
SQLAlchemy's ORM path alternates between about 0.10 s and about 0.88 s while
Django's ORM, Django's SQL and SQLAlchemy's SQL hold steady in the same blocks.
One formulation of one query draws a different plan for certain parameter values
and the other three do not, which is the kind of thing this study exists to
report.

The bound stays as written and the run is reported as failing it. A threshold
amended after seeing the data that failed it is a description of that data, and
the only thing that makes section 8 capable of failing is that it was fixed
before the pilot ran. `run_system.sh` records every advisory gate failure in
`.gate_failures` so that no such run can reach the results file unremarked.

---

## Disclosure — SQL Server non-indexed also fails section 8.1, for a different reason

The indexed run's disclosure above attributes its section 8.1 failure to
parameter sensitivity, and shows that removing the per-block effect takes its
p90 from 23.50% to 14.70%. The non-indexed run fails the same bound and that
explanation does **not** hold for it:

    campaign                  as 8.1 measures it        block effect removed
    SQL Server indexed        median 2.76%  p90 23.50%  median 2.30%  p90 14.70%
    SQL Server non-indexed    median 3.88%  p90 17.54%  median 4.63%  p90 16.08%
    PostgreSQL non-indexed    median 0.89%  p90  2.04%  median 0.27%  p90  1.14%
    MySQL non-indexed         median 0.79%  p90  2.51%  median 0.25%  p90  1.67%

Removing the block effect barely moves the non-indexed p90 and raises its
median. Whatever varies there varies *within* a block, between paths that saw
identical parameters moments apart, which is the definition of measurement noise
rather than parameter effect. The gate's verdict is correct and the run is
reported as failing.

The failure is otherwise narrow. Median CV 3.88% is inside the 5% bound, only
1.2% of paths exceed 25% against a 5% allowance, section 8.3 passes at 50x, and
completeness and design integrity are clean. It is the p90 alone, at 17.54%
against 15%.

The likely mechanism, stated as a hypothesis rather than a finding, is the
memory envelope. SF1_RERUN_PLAN.md sets a 1.5 GB target for the principal
database cache inside a 2 GB database-memory target and a 3 GB cgroup ceiling.
Without indexes, most of these queries scan LINEITEM, whose SF1 extent is
comparable to that cache, so how much of it is resident when a given path runs
depends on what the previous path evicted. PostgreSQL and MySQL do not show it
at the same magnitude under the same envelope, so it is not a property of the
envelope alone.

Both SQL Server runs are kept, both are disclosed as failing their
pre-registered noise bound, and the two are given separate explanations because
they have separate causes. The estimand is unaffected in both: it is formed
inside a block, where the two arms of each ratio saw the same parameters and ran
adjacent in time.

---

## Disclosure — Oracle indexed fails section 8.1, and the cause is the study's own subject

Oracle's indexed TPC-H misses one of the three noise bounds:

    ok    median CV  1.91%   bound 5.0%
    ok    p90 CV     8.48%   bound 15.0%
    FAIL  share above 25.0%:  6.0%   bound 5.0%
          noisiest: Q20 sqlalchemy/sql   CV 98.62%
                    Q20 django/sql       CV 97.51%
                    Q04 django/orm       CV 58.86%

Five paths of eighty-three exceed 25%, where the bound allows four. Median CV,
p90 and the ceiling margin (126x) all pass, as do completeness and design
integrity.

Q20 is most of it, and it is not noise. Both *SQL* paths take 5-7 s in blocks
1, 3 and 8 and about 0.85 s in the other five, while both *ORM* paths are flat
across all eight:

    django/orm       CV  16.58%   0.287 0.206 0.273 0.207 0.204 0.205 0.202 0.277
    django/sql       CV  97.51%   5.581 0.850 7.122 0.877 0.867 0.862 0.834 4.528
    sqlalchemy/orm   CV   4.33%   0.970 0.861 0.853 0.869 0.867 0.876 0.868 0.858
    sqlalchemy/sql   CV  98.62%   6.459 0.857 5.477 0.866 0.868 0.861 0.833 7.108

The split is by access path, not by framework, and it falls exactly along the
line ANALYSIS_PLAN.md section 2.2 draws: the hand-written baselines interpolate
their substitution parameters as literals, and the ORMs pass them as binds.
Oracle's optimiser sees a different literal in each of the eight blocks and
chooses a different plan for three of them; given a bind it compiles once and
reuses. Both ORM paths being flat while both SQL paths swing by 8x is that
difference, measured.

Removing the per-block effect does not help here and makes the figure worse -
6.0% becomes 8.4% - precisely because the effect is not a block effect. Within a
single block the SQL paths are slow and the ORM paths are fast, so normalising
by the block's median cannot cancel it.

Q04's django/orm path is the other contributor, drifting from 0.566 s to 1.953 s
across the eight blocks while its three companions hold between 1.07 s and
1.34 s. That one is unexplained and is disclosed as such.

The bound stays as pre-registered and the run is reported as failing it. This is
now the third such disclosure, and the three have three different causes:
parameter sensitivity (SQL Server indexed), within-block variability (SQL Server
non-indexed), and literal-versus-bind plan selection (Oracle indexed). A single
bound catching three unrelated phenomena is a sign the statistic is coarse, not
a sign the runs are bad - but amending it now, after seeing which runs it
caught, would make it a description of this data rather than a test of it.

---

## Disclosure — Oracle non-indexed fails section 8.3, and no declared ceiling would satisfy it

Oracle's non-indexed TPC-H passes all three noise bounds - median CV 1.38%,
p90 9.89%, nothing above 25% - and fails the ceiling margin:

    FAIL  slowest completed execution 672.191 s   margin 1x, bound 5.0x
          slowest is Q17 django/orm

Q17's Django ORM path completed on all eight blocks. Nothing was truncated and
nothing was censored; the cell is fully measured. What fails is the safety
margin the bound asks for: 672 s against a 900 s ceiling leaves 1.3x, and
section 8.3 wants 5x so that a slower substitution set could not have been
silently cut off.

The plan's declared escalation does not reach it either. The retry ceiling of
2700 s gives 4.0x on a 672 s path, still short of 5x; satisfying the bound would
need about 3400 s, a value that appears nowhere in the plan. Inventing one now
to make this run pass would be choosing a threshold to fit the data it is
supposed to test.

So the run is kept and reported as failing. The risk the bound guards against -
a parameter set slow enough to hit the ceiling, turning a measured cell into a
censored one without anyone noticing - did not materialise here: all eight
blocks of all four paths completed, and the gate's own completeness section
records zero executions failing for an undeclared reason. But the margin is
genuinely thin, and a reader should know that Q17 on Oracle without indexes came
within 25% of the ceiling.

This is the fourth disclosure and the second distinct bound. Of the eight TPC-H
campaigns, four pass every bound (PostgreSQL and MySQL, both configurations) and
four are disclosed: SQL Server indexed and non-indexed and Oracle indexed on
section 8.1 for three different reasons, and Oracle non-indexed on section 8.3.

---

## C43 — the resolution bound was applied to half the grid

ANALYSIS_PLAN.md section 8.1 sets a bound on how much a measurement moves when
nothing changes: median CV at or below 5%, p90 at or below 15%, at most 5% of
paths above 25%. `sf1_tables.py` computed it from the block measurements and
emitted a row per campaign. There are sixteen campaigns and it emitted eight.

The eight it emitted are the TPC-H ones, because `path_cvs` skips any filename
containing `tpcc` — a filter written when the analytical noise figure was the
only one anybody was computing, and never revisited. The transactional latency
files have carried a `cv_pct` column since the campaign ran. Nothing read it.

What that column says, over all 160 transactional paths:

| section 8.1 | bound | worst TPC-H campaign | TPC-C, pooled |
|---|---|---|---|
| median CV | <= 5% | 3.88% | **12.70%** |
| p90 CV | <= 15% | 23.50% | **42.80%** |
| share above 25% | <= 5% | 8.4% | **30.0%** |

All eight transactional campaigns miss all three parts, with campaign medians
from 8.65% to 20.20%. The two CVs are not the same quantity and the difference
runs the wrong way for us: a TPC-H path varies across eight blocks that each
draw their own substitution parameters, so it carries parameter sensitivity as
well as noise, while a TPC-C path varies across three repetitions of one draw.
The bound written for the larger quantity is failed by the smaller one.

The paper's largest claim — analytical overhead near 1%, transactional near 87%,
two orders of magnitude apart — was the only quantity in the results section with
no resolution stated beside it, which is the exact charge section 2 lays against
the prior literature.

The gap survives: 86.8% against a 12.70% floor is not a floor artefact. What did
not survive is the per-transaction ranking that was read off the same cells
("the transaction each framework handles worst is not the same one"), which
rested on Delivery at +143.7% against +150.0% — six points, eight cells per
framework, at a p90 spread of 42.80%. That claim is withdrawn from section 6.

`t_noise` now emits all sixteen campaigns and the caption states which quantity
each row is. A bound is not a bound if it is only computed where it passes.

---

## C44 — the cross-framework comparison was licensed on the half where it cannot fail

Comparing Django's overhead against SQLAlchemy's divides by two different
denominators, and section 3 licenses that by showing the denominators agree.
Across the 1,368 TPC-H blocks where both hand-written baselines ran the same
query on the same parameters, Django's is a median 0.13% faster, p10 -4.6%, p90
+2.5%. That is a real check and it passes.

It was never run on the transactional cells, which is where the paper leaned on
the comparison hardest — 90.5% against 69.2% in the abstract, a per-transaction
ranking in section 6, and two dashed curves in the throughput figure. Run now,
over the 40 paired TPC-C cells:

| | median | p10 | p90 | beyond 5% | range |
|---|---|---|---|---|---|
| TPC-H, per block | -0.13% | -4.6% | +2.5% | 17.3% | 0.48x-2.08x |
| TPC-C, per cell | -3.99% | -38.1% | +39.2% | **75.0%** | **0.45x-2.15x** |

Three quarters of the transactional cells have baselines more than 5% apart. The
throughput runs show it more sharply still: Django's hand-written path is a
median 1.33x SQLAlchemy's at one client and 1.98x at sixteen, on the same
transactions against the same database.

The cause is ours, and it is C20's shape with the sign reversed. Django's
transactional baseline executes through `connection.cursor().execute`, which is
close to DBAPI-direct:

    django_app/tpcc_queries/t2_payment.py:  def run_transaction_sql(connection)

SQLAlchemy's executes through `session.execute(text(...))` on an ORM `Session`:

    sqlalchemy_app/tpcc_queries/t2.py:      def run_transaction_sql(session)

The Session carries transaction bookkeeping, result-proxy construction and
commit-time work on every one of a transaction's 3 to 60 statements. So
SQLAlchemy's *baseline* is charged for the Session, which inflates its
denominator and deflates its measured overhead relative to Django's.

The analytical baselines do not have this problem — both build
`dict(zip(columns, row))` off a fetchall and both sit at the same layer — and
they agree at a median baseline of 1.33 s, where a few hundred microseconds per
statement cannot show. The check was validated in the regime where it cannot
fail and applied in the regime where it matters most.

Correcting it needs a re-measurement with SQLAlchemy's baseline moved to a
`Connection` from `engine.connect()`, and the host is gone. So the paper states
the asymmetry in section 3, makes every cross-framework transactional statement
in milliseconds — which does not divide by the contaminated denominator — and
compares no transactional ratio across the two frameworks.

---

## C45 — a campaign was scored against a ceiling its own rows do not record

C42 fixed `run_block.py` to write `client-side:2700` where it had written
`client-side`, and taught `pilot_gate.py` to parse it. The fix is right. What
followed from it is not.

`path_cvs` resolved a campaign's ceiling as the largest value *any* of its rows
could be parsed for. SQL Server's indexed campaign records:

    client-side          1480 rows
    client-side:2700       52 rows

The 52 are the Q13 cell, re-run after C42 landed. The other 1,480 are the
campaign, and they carry no number at all. Reading 2700 s off the 52 scored the
whole campaign at 2700 / 232.5 = 11.6x and passed it. Against the 900 s
ANALYSIS_PLAN.md section 8.3 declares as the default, the same campaign is
3.87x and fails.

C42's note says the campaign "was deliberately run at 2700 s". Two things
qualify that. Section 8.3 declares 2700 s as the *retry ceiling for a censored
cell, applied once*, and no cell in that campaign was censored, so no retry
fired. Its other escalation — a pilot path between 180 s and 900 s raises the
ceiling for that query on that system *before the campaign* — cannot apply
either, because Q18 is not among the pilot's six queries. And the parser that
makes 2700 s legible to the gate was committed at 2026-09-06 16:53, after that
campaign's rows were written between 05:24 and 08:53 the same day.

So the value is pre-registered and the rule under which it reached this campaign
is not. A bound the analysis can only reach by reading rows written after the
run is not a bound the run was held to.

`path_cvs` now accepts a campaign's recorded ceiling only when *every* row
records one, and otherwise scores it against the declared default. SQL Server
indexed is reported as missing the margin at 3.87x. It was already missing the
p90 and the tail, so the count of failing analytical campaigns stays at four and
what changes is that one of them fails a bound the paper had reported it as
passing.

C42 remains correct as a harness fix and this is the analysis defect it
concealed. The two together are the register's most-repeated shape: nothing
failed, the number was plausible, and it was the number we wanted.

---

## C46 — a percentile interval was reported from five clusters

`t_headline` printed a 95% bootstrap interval on all four rows. On the two
transactional rows that interval resamples five clusters, because TPC-C has five
transactions, and five is not enough for the statistic it was printing.

The bootstrap draws 5 clusters with replacement, so it has 5^5 = 3,125 possible
resamples and the median of each is one of a small set of values. Enumerated:

    Django       43 distinct medians out of 3,125 resamples
    SQLAlchemy   65 distinct medians out of 3,125 resamples

So `[+63.1, +144.9]` was two of 43 reachable values, set in brackets that read as
a continuous interval and rounded to a tenth of a percent. The number is not
wrong; the precision it advertises does not exist.

The same table already says that the exact signed-rank test cannot report below
0.0625 on five clusters, and that the transactional claim rests on the effect
against the resolution rather than on a p-value. The interval was the one column
still asserting conventional precision on that half of the grid.

Those rows now carry the range of the five transaction medians:

    Django       +23.9% to +150.3%
    SQLAlchemy    +3.8% to +150.0%

which is what those 40 cells actually say about spread, and which a reader can
check against the per-transaction rows of `tab_per_statement` directly.

Removing two `clustered_bootstrap` calls shifts the RNG stream for the tables
built after it. Every median in `tab_sensitivity` is unchanged and its interval
endpoints move by at most 0.6 points, which is resample noise. The analytical
rows keep their interval: 22 query clusters is not five.

Found by a referee reading the manuscript, like C43 to C45. It changed what the
paper claims and not what it measured.

---

## C47 — one statistic, two values, because the tables shared a generator

`tab_headline` prints the pooled TPC-H median and its query-clustered interval.
`tab_sensitivity`'s first row, labelled "none (as reported)", removes no group,
so it is that same figure by construction. They disagreed:

    tab_headline      TPC-H, Django   +1.13%  [+0.5, +3.6]
    tab_sensitivity   none (as rep.)  +1.13%  [+0.5, +3.7]

The medians match because a median is deterministic. The intervals did not,
because `main()` built one `random.Random(SEED)` and threaded it through every
table in the run. `clustered_bootstrap` drew from wherever the stream happened
to be, so a table's resamples depended on how many resamples the tables before
it had taken. Adding or removing a table upstream moved the interval printed
downstream, and C46 had done exactly that a few commits earlier: dropping two
bootstrap calls from `t_headline` shifted every endpoint in `tab_sensitivity`
by up to 0.6 points.

The value was never wrong in the sense of being outside what the data support.
Both endpoints are legitimate draws from the same 2,000-resample percentile
interval. What was wrong is that the paper printed two of them for one quantity,
in two tables a reader is invited to compare, and had no way to say which.

`clustered_bootstrap` now seeds from the sample:

    def bootstrap_seed(cells):
        key = "|".join("%s:%.12g" % (q, th) for q, th in sorted(cells))
        return SEED ^ zlib.crc32(key.encode("utf-8"))

so the interval is a function of the data and nothing else. Call order stops
mattering, and so does which tables a run happens to build. Every call site
dropped the shared generator; the parameter survives for callers that still
pass one, and nothing in the repository does.

`tests/test_sf1_tables.py` now asserts that the two tables agree, rather than
that either equals a transcribed constant. The property worth holding is that
one statistic has one value wherever the paper prints it.

Found during manuscript review, like C43 to C46, by a reader comparing two
tables against each other rather than against the data.
