# ORM overhead: Django and SQLAlchemy against hand-written SQL

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22649752.svg)](https://doi.org/10.5281/zenodo.22649752)

The artifact for *Two Workloads, Two Orders of Magnitude: ORM Overhead on Four
Database Systems*. Archived at
[10.5281/zenodo.22649752](https://doi.org/10.5281/zenodo.22649752), which
resolves to the latest version.

    4 database systems
      x 2 frameworks (Django 6.0.8, SQLAlchemy 2.0.52)
      x 2 schema configurations (indexed, non-indexed)
      x 27 workloads (TPC-H Q01-Q22 + TPC-C T1-T5) at scale factor 1
    = 432 cells, 416 measured on both access paths

Every cell is emitted whether or not it was measured. One that was not carries a
status and a reason in words, because a gap and a zero that look alike is the
defect this harness was rebuilt to remove.

## Start here

- `MANIFEST.md` - what this export contains, what it withholds and why, and what
  running the analysis over it reproduces.
- `docs/CORRECTIONS.md` - the 47 defects found while building,
  validating and reviewing the harness. This is the register the paper's
  Section 4 groups into six failure modes.
- `ANALYSIS_PLAN.md` - the resolution bounds, fixed before the pilot ran. Four
  campaigns fail them, which is only meaningful because they were fixed first.
- `PLAN.md` - the campaign as executed.

## Reproducing

    python3 -m venv venv && source venv/bin/activate
    pip install -r requirements-sf1.txt
    export PYTHONPATH=. TPCH_SF=1

    python3 scripts/4-analysis/sf1_analysis.py --scale 1
    python3 scripts/4-analysis/sf1_tables.py   --scale 1 --outdir tables
    python3 scripts/4-analysis/sf1_referee.py  --scale 1

The last of those prints the working behind the paper's prose claims: the
pre-registered bound on each campaign, whether the two frameworks' baselines
agree, the ceiling each campaign's rows record, what excluding Query 18 buys,
the clustered significance, the informative censoring, and the per-statement
figures.

`REPRODUCE.md` covers re-running the measurements, which needs the four engines
loaded under the envelope `docs/ENVIRONMENT.md` describes.

## One system's results are withheld

A vendor's developer licence forbids disclosing benchmark results for its system
without written approval. Its 108 cells are here as rows with empty
measurement columns and the reason in `status_note`, and its raw timing files
are not. `MANIFEST.md` gives the full account, including what the analysis
returns without them and why that number is already in the paper.

## Licence

MIT, see `LICENSE`. The TPC-H and TPC-C derived workloads are covered by the
TPC's fair-use policy: neither is a TPC benchmark and neither is comparable to
published TPC results.
