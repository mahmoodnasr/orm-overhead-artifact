# B8 follow-up findings

Status: four completed ORM/baseline cases. All independent result, plan,
source, input and configuration checks pass. The requested three-to-five-case
empirical follow-up is complete; its findings are integrated into Section V.

## What is new

Actual execution plans were captured on the original Linux host on 19 September
2026 for Django's indexed Commercial System A Q18 and Q17 and non-indexed Oracle
Q17 and Q20, each with its own SQL baseline. Each used qualification input set 0, SF1 row counts, the retained
query sources, and recorded indexes, parameter bindings, versions and resource
settings. All 102 paper query-source hashes match the live checkout.

The captured plans belong to fresh, identified executions. They are not the
historical plans behind the paper's eight-input overhead estimates. The current
commercial database build differs from an older host setup note; the full
current version is retained in the private inventory. The historical build
was not attached to each timing row, so its exact relationship remains unknown.

For Commercial System A, the collector first ran the original Django functions, then replayed their
captured statements through the same backend and connection with runtime plan
collection enabled. It verified identical driver-level SQL and parameter
bindings between each function execution and replay. Every complete result
matched between the ORM and baseline, and between the function and replay.
Checks retain column identity, duplicates, and result order; only column-name
case and midnight datetime/date representations are normalized. Oracle plans
come from the actual function calls with session statistics enabled and the
client statement cache disabled. Their SQL and bindings also match the first
passes exactly; no optimizer hints or query-source changes were introduced.

## Indexed Commercial System A Q18, Django

All 57 result rows agree exactly. The ORM-generated plan uses an order-first
strategy: it sorts 1,500,000 orders and executes the inner quantity aggregate
1,500,000 times. The corresponding LINEITEM index seek executes 1,500,000 times
and the heap row lookup executes 6,001,215 times. Only 57 orders satisfy the
quantity condition. The row lookup alone records 609,009 physical reads;
the plan's wait statistics record about 217.5 seconds waiting for page reads.

The SQL baseline instead scans all 6,001,215 LINEITEM rows once and aggregates
them before retaining the 57 qualifying orders. It then performs the small
set of lookups needed for the output. Both plans contain 21 operators, which
illustrates why operator counts alone do not characterize the work performed.

The ORM statement declares a bound NUMERIC threshold; the baseline embeds the
literal 300. The ORM plan records a row-goal estimate of about 333 rows at the
order sort, while 1,500,000 rows actually flow through it. These observations
identify a costly execution strategy, but do not isolate which SQL or
parameter-handling difference caused that strategy to be selected.

The plan reports database elapsed times of 307.213 seconds (ORM-generated
statement) and 4.256 seconds (baseline). These are instrumented diagnostic
observations, not replacements for the paper's paired eight-input estimate.

Evidence: `evidence/commercial-q18-django/`, especially both `.sqlplan` files,
`case.json`, `capture-*.json`, and the two result-comparison files. Important
ORM plan nodes: 8 (sort), 15 (repeated aggregate), 19 (index seek), 21 (row
lookup). Baseline nodes: 21 (aggregate), 22 (single LINEITEM scan).

## Indexed Commercial System A Q17, Django

The one-row result agrees exactly. Both paths identify 204 qualifying parts and
6,088 associated line items. The ORM plan additionally scans all 6,001,215
LINEITEM rows to construct an aggregate, recording 116,259 logical reads on
that scan. The baseline instead reuses the selected line-item rows through
temporary stored intermediate results (spools). Its plan does not contain the
additional full LINEITEM table scan.

The plan reports database elapsed times of 3.431 seconds and 0.754 seconds.
This fresh case supports different database work as a contributor to the
observed gap. It does not support a claim that the ORM always re-executes the
aggregate separately for every line-item row: this captured plan transforms
the query and performs the additional table scan once.

Evidence: `evidence/commercial-q17-django/`. Important ORM node: 21 (full scan;
6,001,215 actual rows read, 6,088 emitted). Baseline nodes 5, 22 and 23 retain
and reuse the selected intermediate rows.

## Non-indexed Oracle Q17, Django

The complete one-row result agrees exactly across the original functions and
accepted captures: 348406.0542857142857142857142857142857143. No rounding was
needed. Both paths select 204 parts and join 6,088 line items.

The ORM plan scans LINEITEM once for the outer join, then starts a separate
full LINEITEM scan 771 times for the correlated average. That inner scan
records 71,493,288 consistent buffer gets and 71,484,036 reported physical reads;
its cumulative output is 23,970 rows, not the number of rows examined. The
baseline scans LINEITEM once and applies a window operation to the 6,088 joined
rows. Its total consistent buffer gets are 96,100, versus 71,589,388 for the ORM.
These counters expose repeated work in this fresh execution. They do not prove
that changing the correlation alone would choose the baseline strategy.

The accepted function captures took 462.919 seconds and 0.753 seconds. The plan
root reports 462.904 seconds and 0.741 seconds respectively. These are diagnostic
observations, not replacements for the eight-input paired estimate. The 771
inner starts also show why one must not assume one subquery evaluation for each
of the 6,088 joined rows.

Evidence: `evidence/oracle-q17-django/`. ORM SQL ID `8jvw7fu8a54t8`, child 1,
plan hash 2515364962; baseline SQL ID `arpakbk36szp2`, child 1, plan hash
3341365018. Key ORM nodes: 6 (aggregate) and 7 (inner full scan); baseline nodes
3 (window sort) and 6 (single LINEITEM scan).

The first requested capture finished but had no operator counters. Its files
remain in `oracle-q17-django-attempt1`. A controlled tiny probe reproduced the
client statement-cache issue and verified the fix. The retry preserved the
completed warmup after rechecking sources, indexes, counts and inputs. Its
plan hash matches the earlier unprofiled ORM plan; the accepted child cursor
adds the required runtime counters. See `PROTOCOL.md` for the full deviation.

## Non-indexed Oracle Q20, Django

All 186 rows agree exactly by named columns and row order across the original
functions and accepted captures. The qualification values are `forest`,
`CANADA`, and the half-open date window from 1994-01-01 to 1995-01-01. The end
date is generated by the retained parameter module's 12-month expansion.

The ORM plan starts the inner full LINEITEM scan 366 times for candidate
part--supplier pairs. That scan records 33,938,448 consistent buffer gets and
433 output rows after its predicates. The baseline scans LINEITEM once,
emitting 909,455 rows within the date window, then joins and groups relevant
quantities before applying the available-stock condition. Its total consistent
buffer gets are 112,815, versus 33,958,535 for the ORM. Both finish with the same
186 supplier rows.

The accepted function captures took 267.768 seconds and 1.380 seconds. Plan-root
times are 267.735 seconds and 1.340 seconds. As with Q17, repeated scans are
visible in this execution; the comparison does not isolate the effect of SQL
formulation from parameter binding or explain every historical configuration.

Evidence: `evidence/oracle-q20-django/`. ORM SQL ID `0g5bd0cqmvf92`, child 1,
plan hash 3126194028; baseline SQL ID `2g162gmj3q1fy`, child 1, plan hash
1111411882. Key ORM node: 15 (repeated full scan); baseline nodes 12 (single
scan), 7 (grouping) and 6 (stock filter).

## Limits and restoration

One selected input per case; one warmup and one instrumented capture per path;
fixed execution order; no database cache flushing. Oracle Q17 includes the
documented extra execution and collector retry. Recreated indexes and refreshed
statistics are documented. Memory-grant feedback reports adjustment in the
captured commercial plans, so these are not evidence of stationary repeated
latency. The comparisons do not separate SQL formulation, parameter handling,
optimizer selection, cache state and client costs causally.

After both commercial cases, the fifteen newly created secondary indexes were
removed. The initial primary-key index inventory and SF1 row counts were
restored and rechecked. No original timing files or query sources were edited.

Oracle remains on the retained SF1 dataset, primary keys only, and server
version 23.7.0.25.01. Initial and final process checks confirm CPU affinity 0-1.
After capture, its indexes, row counts, source hashes and table-statistics
inventories were unchanged. The four temporary diagnostic grants were revoked;
an ordinary-account read check independently confirmed their removal. The
laptop's normal power settings were restored and read back successfully.

These four cases cover all three requested query numbers. SQLAlchemy's indexed
Commercial System A Q17 remains an optional fifth case; wider parameter
coverage and the three-path attribution experiment are separate future work.
