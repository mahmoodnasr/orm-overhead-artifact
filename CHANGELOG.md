# Changelog

## v1.1.0 — 9 September 2026

Align the public artifact with *How Portable Is ORM Query Performance? Evidence
from Four Database Systems* and provide a runnable four-system reproduction path.

- Add one-command integrity checking and offline reproduction with pinned analysis dependencies.
- Rebuild the full four-system analytical, transactional and sensitivity results.
- Preserve the 18 previously public raw measurement CSVs byte for byte.
- Include all six Commercial System A measurement files and all 108 coverage rows,
  retaining every numerical value and using an anonymous database label.
- Format the selected source and fix portable imports/settings in the runner and validator.
- Fix the index manager's project root and make parameter checks fail under pytest.
- Add checks for corrupted files, missing pairs, duplicates, zero runtimes and missing measurements.
- Replace stale documentation, citations, duplicated guides and superseded analysis pipelines.
- Add continuous verification and a deterministic ZIP release builder.

No new database measurements are introduced. The analysis plan and correction
register remain as historical evidence; prior public versions remain in Git tags.

## Earlier releases

See the existing v1.0.0 and v1.0.1 release notes and corresponding tagged snapshots.
