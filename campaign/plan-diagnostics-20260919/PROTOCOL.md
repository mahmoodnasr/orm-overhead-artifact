# B8 execution-plan follow-up — 19 September 2026

This is a new diagnostic follow-up on the original Linux host, not recovery of
the historical plans and not a replacement for the paper's timing campaign.

## Scope fixed before captures

Start with qualification input set 0 for Oracle non-indexed Q17 and Q20
(Django), and Commercial System A indexed Q18 (Django). If capture succeeds,
extend to indexed Commercial System A Q17. Each ORM is compared with its own
handwritten SQL baseline. These selected cases and inputs are not a sample of
all queries or all eight historical parameter sets.

Use the retained SF1 query sources without changes. Record their hashes,
the Git revision, actual server/client versions, exact parameters, database
row counts, indexes, session settings, and host resource controls. Check the
recorded parameters against the historical timing rows. Store new evidence
outside the old measurement directories. Record any environment difference.

Run the native engines one at a time with the original host controls and client
CPU affinity. Preserve initial index inventories; restore indexes temporarily
created or removed for the follow-up. No application data are intentionally
changed. Database statistics may be refreshed with the retained campaign
script; record that action because historical statistics cannot be recovered.

Warm up the actual ORM and baseline functions, recording their generated SQL,
bound parameter values/types, full returned values, and elapsed time. For
Commercial System A, replay each captured statement through the same Django
backend and connection with STATISTICS XML enabled, retaining actual plans and
complete results. This preserves backend parameter rewriting and bindings;
record and verify identical driver-level SQL and parameter values. It is a
statement replay, not a measurement of ORM client overhead. For Oracle, enable
session-level statistics and capture DISPLAY_CURSOR for the actual executed
statement, retaining plan identity and runtime operator statistics where
privileges permit. No plan-cache flushing or query rewriting.

Compare results by named columns, preserving duplicates and checking query
ordering. Preserve exact values; numeric tolerance, if necessary, must be
explicit and justified. An error, mismatch, missing runtime plan, or failed
environment check remains visible and is not counted as a completed case.

Instrumented elapsed times are diagnostic observations with instrumentation
and cache/order effects. They must not be pooled into the published ratios.
The diagnostic client limit is 1800 seconds per call, separate from the
historical campaign's limits. No result is accepted solely because it completed
inside that limit; plan identity, actual counters and result checks also pass.
Plan differences support bounded explanations for these fresh executions;
they do not prove which plan ran historically or establish a causal effect of
an isolated SQL change. A stronger attribution experiment is separate work.

During the long Oracle Q17 calls, lightweight status queries used a separate
connection. One in-progress plan snapshot was retained for diagnosing a possible
timeout. It is explicitly marked incomplete; its counters may refer to an
earlier execution and are not used as final evidence. Completed captures and
their exact statement identities are required for the final comparisons.

## Oracle collector correction

The first Q17 warmup completed in 1406.661 seconds and its result matched the
baseline exactly. The first requested capture also completed (455.790 seconds)
but returned no runtime operator counters, so it was not accepted as evidence
of a completed plan case. It remains in `oracle-q17-django-attempt1`.

A small controlled probe reproduced the missing counters when the statement
had been cached before `statistics_level=ALL`. Setting the client connection's
`stmtcachesize` to zero produced counters for the same SQL and bindings; a fresh
session also passed. The corrected collector disables this client statement
cache before requesting statistics. It does not flush the database plan cache,
alter query sources, or insert optimizer hints.

The Q17 retry reuses the complete first-pass records after rechecking source
hashes, indexes, counts and input values. Its provenance file identifies the
earlier inventory. This case therefore includes an additional completed ORM
execution before the accepted capture. Instrumented observations remain outside
the main timing estimates. The controlled cache probe and collector versions
are retained so this deviation is explicit.

## Capture references

- the vendor, the vendor's actual-plan capture: <vendor documentation>
- Oracle, DBMS_XPLAN: https://docs.oracle.com/en/database/oracle/oracle-database/26/arpls/DBMS_XPLAN.html
- Oracle, STATISTICS_LEVEL: https://docs.oracle.com/en/database/oracle/oracle-database/21/refrn/STATISTICS_LEVEL.html
- python-oracledb, connection statement cache: https://python-oracledb.readthedocs.io/en/latest/api_manual/connection.html#Connection.stmtcachesize

The commercial capture keeps STATISTICS XML and the target SELECT on the same
cursor because MARS session handling did not preserve the option when a
separate cursor closed. A tiny read-only collector probe verified one actual
plan with runtime counters, unchanged driver SQL/bindings, and equal results.
Probe records are not counted as outlier cases.
