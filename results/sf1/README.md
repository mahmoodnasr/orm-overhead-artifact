# Frozen SF1 data

`all_results.csv` includes all 432 planned cells: 336 measured analytical cells,
12 timeouts, four inexpressible cells and 80 measured transactional cells.
All 108 Commercial System A rows are included with their original values and
statuses. Its data identifier and filename prefix are `commercial_a`.

The 24 measurement CSVs retain all raw analytical, transaction and throughput
records. The 18 inputs for PostgreSQL, MySQL and Oracle are unchanged from
v1.0.1. In the six Commercial System A files, only the database name and two
diagnostic notes were relabeled; every measurement value remains unchanged.

See `../../PUBLIC_INPUTS.json` for checksums and preservation checks, and
`../../docs/DATA_DICTIONARY.md` for units and interpretation.
Run `python review.py reproduce` from the repository root to rebuild all four
systems' results.

These are the frozen paper inputs. Use separate output paths for new experiments;
do not append new measurements to these CSVs or hand-edit their coverage grid.
