# Release scope and provenance

This update includes the complete retained measurements for the 9 September 2026
revision of *How Portable Is ORM Query Performance? Evidence from Four Database
Systems* in the existing public repository.

## Included data and results

- All 432 planned coverage rows: 416 measured, 12 timeouts and four inexpressible cells.
- All 24 raw measurement CSVs across four systems and two index configurations.
- All 108 Commercial System A coverage rows, including 106 measured cells.
- Full four-system analytical, transaction and throughput results, including the
  five paper tables, three figures and seven numerical exports rebuilt offline.
- Query/model source, baseline SQL, setup and timing tools, tests and instructions.

`PUBLIC_INPUTS.json` records the 18 raw inputs unchanged from public commit
`e55d4977f45ef5e92644461120da42a6bca53e67`, the hashes of all 25 current input CSVs,
and the preservation check. The complete manuscript inputs were compared row by
row: all 13,104 rows and every measurement value are retained. Only 3,348 database
labels and two diagnostic notes were relabeled. No measurements were replaced,
rounded, inferred or removed.

Commercial System A is named `commercial_a` in measurement filenames, raw data
and derived CSVs, and “Commercial System A” in the coverage grid, tables and
figures. Diagnostic notes retain their explanation with the system name changed.

The reference results come from the retained full manuscript analysis; only
system identifiers and input paths/checksums were updated. Numeric comparisons
allow `1e-12` absolute and relative tolerance for platform math libraries, while
LaTeX tables must match exactly. All scientific estimates remain unchanged.

## Naming scope

The data and analysis use the anonymous label. Existing benchmark adapters,
driver dependencies and historical technical documentation still identify the
supported database. Earlier public commits and releases also contain identifying
references. Relabeling results therefore does not make the repository anonymous.

## Integrity and source

`MANIFEST.json` records SHA-256 for every release file except itself. A separate
SHA-256 file accompanies a ZIP built with `scripts/release.py`.
`python review.py verify` checks file integrity and dataset completeness;
`python review.py reproduce` additionally checks the full generated results.

The prepared tree excludes local environments, caches, credentials, local database
files and backup archives. The source formatting preserves executable query
expressions and SQL constants. Small import-path fixes allow the analytical
runner, validator and index manager to resolve their checkout. Parameter test
failures raise assertions under pytest. These source fixes do not alter the
retained historical measurements.

The original public analysis plan and correction register remain as historical
methodological evidence. Their older commands are superseded by `REPRODUCE.md`.
