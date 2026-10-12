# Changelog

## v2.0.0 — 12 October 2026

Align the public artifact with the October 2026 revision of *How Portable Is
ORM Query Performance? Evidence from Four Database Systems*. Its results come
from a new measurement campaign, released here with its records.

- Add `campaign/`: revision campaign rc20261008 (8–11 October 2026). The SF1
  analytical grid measured again under a frozen protocol, transactions under a
  24-block matched design, scale factor 2, a separate client, a second server,
  a four-path decomposition of the large gaps, and result validation of all
  twelve censored cells. 728 planned cells, each with its status and reason;
  about 40,000 per-call records with inputs, timings, sessions, full results
  and acceptance decisions; protocols, environment inventories, execution
  plans, the campaign harness and the measured source, byte for byte.
- Commercial System A: data and documentation no longer name the product.
  Its SQL text, plans, server version, configuration and driver messages are
  withheld from the campaign records as SHA-256 placeholders; its plan files
  are withheld and listed in `campaign/WITHHELD.json`. `REPRODUCE.md` no
  longer maps the anonymous label to its adapter, and the correction register
  uses the anonymous label.
- `review.py verify` checks the campaign tree against `campaign/SHA256SUMS`,
  its coverage grid, evidence paths and source bindings. `review.py reproduce`
  rebuilds all 23 campaign reference outputs from the records with the
  campaign's own scripts and re-checks every accepted ORM/SQL pair of phases A,
  D and E from the stored results.
- Apply the two transaction-baseline corrections the campaign measured with:
  Django's SQL Payment now writes the same `h_data` as the other three paths,
  and SQLAlchemy's SQL Order-Status reads the order lines.
- Add `tests/test_campaign.py`: the maintained source executes as the
  measured source, statement for statement.
- Remove a private network address from `scripts/update_manifest.py`.

The September 2026 measurements in `results/sf1/` and their reference outputs
are unchanged; they are the comparison the manuscript reports.

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
