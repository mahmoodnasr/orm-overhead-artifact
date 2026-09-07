# What is in this export, and what is not

This is the depositable subset of the artifact behind *Two Workloads, Two
Orders of Magnitude: ORM Overhead on Four Database Systems*. It is an export
rather than a mirror of the working repository, because that repository's files
and its git history name a system whose licence forbids disclosing benchmark
results for it.

## Here

- The harness: both frameworks' implementations of all 27 queries and
  transactions, the per-vendor overrides, the schema and load scripts, the
  block protocol, and the pre-flight checks.
- The five validation checks and the test suite.
- Every analysis script that produces a table or a figure in the paper.
- `docs/CORRECTIONS.md`, the register of 47 defects.
- `ANALYSIS_PLAN.md`, which fixes the resolution bounds the paper reports four
  campaigns as failing. It is dated before the pilot; that is the whole reason
  those bounds could fail.
- `results/sf1/all_results.csv`: all 432 cells.
- Raw per-block timings for PostgreSQL, MySQL and Oracle: 18 files.

## Not here

108 of the 432 cells belong to one system. Section 6 of that system's
developer licence forbids disclosing benchmark results for it without the
vendor's written approval, so this export carries no timing, ratio or
percentage for it. The cells remain in `all_results.csv` as rows, with empty
measurement columns and the reason in `status_note`, so the grid stays
countable at 432 rather than silently becoming 324.
`results/sf1/measurements/WITHHELD.md` lists the raw files that are absent.

The harness itself ships whole and names that vendor, because the licence
restricts disclosing results and not disclosing that the code supports it. A
reader can therefore tell which system is withheld. The paper says as much: two
of its four systems restrict publication and it names the other one. The
anonymisation keeps results from being attributed to the product, which is what
withholding the numbers enforces.

## What this subset reproduces

Running the analysis over this export does not return the paper's headline
numbers, and it should not. Six of the eight campaigns are here, so the pooled
analytical medians come back as +0.72% for Django over 123 cells and +0.30%
for SQLAlchemy over 127, against the paper's +1.13% and +0.67% over 165 and
171.

Those two figures are already in the paper. Table VII's sensitivity analysis
reports the pooled medians with Commercial System A removed, and the row reads
+0.72% and +0.30%. So this export reproduces a published row exactly, and the
difference between it and the headline is the quantity that table exists to
report rather than a discrepancy. The transactional medians come back as
+88.3% and +71.2% over 30 cells against +90.5% and +69.2% over 40.

## The choice this export made, so it can be revisited

The paper prints that system's overheads under its anonymous label in three
tables and one figure, and a journal will publish them. By that reading the
already-anonymised `results/sf1/analysis/*.csv` could ship too, and 90
more rows would be here.

This export withholds them. Beside a harness that names the vendor in a dozen
paths, an anonymised number is anonymised in form only, and the reading is the
authors' to make against their own licence rather than a script's to assume.
Reversing it is one line: drop the anonymous label from `RESTRICTED` in
`scripts/utils/make_public_artifact.py` and rebuild.

## Rebuilding this

    python3 scripts/utils/make_public_artifact.py --out <dir>

The script re-reads everything it wrote and fails if any exported CSV carries a
measurement on a restricted row, over the whole export rather than the part
that suggested the check.
