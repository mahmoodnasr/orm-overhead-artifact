# Documentation

Two kinds of file live here. Read the first group; treat the second as
background.

## Current — written against the SF10 four-system campaign

| | |
|---|---|
| [`ENVIRONMENT.md`](ENVIRONMENT.md) | what each system was allocated and what it actually ran on — CPU, memory, parallelism, and where allocation and utilisation diverge |
| [`PARALLELISM.md`](PARALLELISM.md) | why MySQL executes every query on one thread, the measured A/B that established it, and the three workarounds that were rejected |

The two files a reader should start from are outside this directory:
[`../README.md`](../README.md) for the findings and
[`../REPRODUCE.md`](../REPRODUCE.md) for the commands that produced them.

## guides/ — background, partly superseded

These were written for an earlier version of the pipeline, when the study was
PostgreSQL-only and the dataset came from `tpch-dbgen` as `.tbl` files. Dataset
generation has since moved to DuckDB and the loaders stream from it, so the
setup steps in them no longer match the code. Each affected file carries a note
saying so at the top, and the dead commands have been replaced with pointers.

They are kept because the conceptual material is still accurate and still
useful: what the MOEF framework does, how the analysis is structured, how to add
a query or a vendor.

| | |
|---|---|
| `01-GETTING-STARTED.md`, `02-INSTALLATION.md`, `03-RUNNING-BENCHMARKS.md` | orientation. For anything you intend to *run*, prefer `REPRODUCE.md` |
| `04-MOEF-FRAMEWORK.md`, `MOEF-QUICKSTART.md`, `MOEF-RESULTS-GUIDE.md`, `MOEF-TROUBLESHOOTING.md` | the plan-analysis framework in `scripts/3-moef/` |
| `05-ANALYSIS.md` | how the derived tables and figures are produced |
| `06-TROUBLESHOOTING.md`, `07-EXTENDING.md` | failure modes, and adding a query or DBMS |
| `QUICK_REFERENCE.md`, `CONTRIBUTING.md`, `REPRODUCIBILITY.md` | command summary and conventions |

## A note on MOEF

`scripts/3-moef/` attributes a difference in runtime to a difference in plan —
index utilisation, join method, join enumeration, predicate handling. It is
included because the study's central claim is mechanical rather than
statistical: that ORM overhead is a property of the *statement a formulation
produces*, not of the framework, and that claim can only be settled by reading
plans.

The plans that support the reported findings were captured directly by
`scripts/4-analysis/collect_plans.py` (PostgreSQL),
`collect_plans_oracle.py` and `collect_plans_sqlserver.py`, and live under
`results/corrected/`. The MOEF pipeline is the more general framework around
that idea and is not on the path that generated `results/all_results.csv`.
