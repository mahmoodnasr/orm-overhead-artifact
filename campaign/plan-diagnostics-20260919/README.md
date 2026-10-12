# B8 execution-plan evidence

This package records a fresh diagnostic follow-up on 19 September 2026 for
selected SF1 analytical outliers. It supplements the paper's original campaign;
it does not replace its measurements or recover the plans used historically.

## Start here

- `STATUS.md`: current capture and manuscript status.
- `FINDINGS.md`: supported interpretation, exact operator counts, and limits.
- `PROTOCOL.md`: scope, capture procedure, comparison rules, and monitoring.
- `evidence/independent-verification.json`: independent checks for each case.
- `evidence/operator-summaries.json`: extracted plan operators for inspection.

## Cases

Every case compares Django with its own handwritten SQL baseline using
qualification input set 0. A case is complete only when its actual plans,
complete results, source and environment records, and comparison checks pass.

| Folder under `evidence/` | Configuration | Query |
|---|---|---|
| `commercial-q18-django` | Commercial System A, indexed | Q18 |
| `commercial-q17-django` | Commercial System A, indexed | Q17 |
| `oracle-q17-django` | Oracle, primary-key indexes only | Q17 |
| `oracle-q20-django` | Oracle, primary-key indexes only | Q20 |

`case.json` records the actual input values and links them to historical rows
by query, framework, parameter-set ID, SF1 and index configuration. This is
provenance for a new execution, not proof of an identical historical plan.

## Files within a completed case

- `inventory.json`: source hashes, software versions, table counts, index and
  statistics inventories, resource settings, and initial host checks.
- `warmup-sql.json` and `warmup-orm.json`: original function executions, full
  returned values, SQL and parameter bindings, and elapsed times.
- `capture-sql.json` and `capture-orm.json`: instrumented executions, returned
  values, and driver-level statements and bindings.
- `capture-*-plan-0.sqlplan`: actual commercial plans with runtime counters.
- `capture-*-plan.txt` and `capture-*-plan.json`: Oracle display plans and
  operator runtime counters tied to the executed SQL ID and child cursor.
- `*-result-comparison.json`: column-aware, ordered comparisons preserving
  duplicates and exact numeric values. No rounding or value sorting is used.
- `index-verification.json`, `host-after.json`, `completion.json`: final gates.

Oracle's `progress/` folder, when present, contains a snapshot taken while the
query was active. It is incomplete and is excluded from the completed evidence.

## Rechecking the evidence

From this directory, run:

```
python3 verify_evidence.py evidence
python3 summarize_plans.py evidence
```

The verifier reads the retained results independently of the capture process.
It fails when a planned case is missing or any required check fails. The
summarizer extracts operators without making causal claims.

`capture.py` contains the collector, and `collector-versions/` preserves the
exact versions identified by each inventory. The clean benchmark revision and
the 102-file snapshot are recorded in the case inventories. The paper's query
snapshot remains in `reproducibility/query-source/`; it was not edited.

## Interpretation and publication scope

The original function runs precede the instrumented runs in a fixed order;
caches are not cleared. There is one input and one instrumented execution per
path. Commercial plans are collected by replaying the statement through the
same backend and connection, with identical driver SQL and bindings. Oracle
plans are collected from the actual function executions after enabling session
statistics. These observations cannot estimate a stable timing distribution or
isolate the causal effect of SQL structure, bindings, cache state, or client
overhead.

Raw inventories preserve the engine identities and local environment details
needed for verification. The manuscript uses Commercial System A consistently.
This local package is separate from the public release cited in the paper.
