# Release scope and provenance

Version 2.0.0 accompanies the October 2026 revision of *How Portable Is ORM
Query Performance? Evidence from Four Database Systems*.

## Included

- **Revision campaign rc20261008** (`campaign/`): the 728-cell coverage grid of
  phases A–G and V, about 40,000 per-call records with their acceptance
  decisions, the frozen protocols, execution plans of the controller, run
  inventories, dataset fingerprints, execution-plan evidence, the October
  four-path diagnostics, the September plan diagnostics, the campaign harness,
  and the 109 measured source files byte for byte. The four analysis runs the
  manuscript reports are included as reference outputs.
- **September 2026 SF1 measurements** (`results/sf1/`): all 432 coverage rows
  and the 24 raw measurement CSVs, unchanged from v1.1.0, with their reference
  outputs in `analysis/reference/`.
- Query and model source, handwritten baselines, setup and timing tools, tests,
  and instructions.

## Integrity

`MANIFEST.json` records the SHA-256 of every top-level release file, including
`campaign/SHA256SUMS`, which records the SHA-256 of every file in the campaign
tree. `python review.py verify` checks both. `PUBLIC_INPUTS.json` records that
the September inputs are unchanged from the earlier public releases. A
SHA-256 file accompanies the ZIP built by `scripts/release.py`.

## Naming

Commercial System A is anonymous under the licence of its software, which
restricts publishing vendor-attributed benchmark results. In data and
documentation it is `commercial_a` or “Commercial System A”. The release
withholds this system's SQL text, execution plans, server version,
configuration and driver messages from the campaign records; SHA-256
placeholders keep each record's structure and bindings. Its plan files are
listed in `campaign/WITHHELD.json` with their original hashes.

The benchmark adapters for this system remain in the source so that its cells
can be measured again. A reader of the code can therefore infer the product,
and earlier public releases and commits name it. Relabelling the results does
not make the repository anonymous.

## Provenance of the campaign copy

The campaign tree was copied from the campaign record.
`campaign/release-provenance.json` lists every file that differs from its
original, with both hashes; every other file is a byte-identical copy. Besides
the anonymisation above, the copy replaces private host details: home
directories, host and user names, network addresses, disk serial numbers, an
unrelated service on the host, and desktop applications on the client. The
controller's state and logs, the synchronisation and backup tools, a privileged
host-administration helper and internal working notes are not released; none
holds a measurement. The campaign's analysis scripts, rerun on the released
records, reproduce every reference output (`review.py reproduce`).

## Source fixes in this release

The maintained source includes the two transaction-baseline corrections that
the campaign applied before measuring transactions (`campaign/rc20261008/patches/`).
`tests/test_campaign.py` holds the maintained source to the measured source
statement for statement; the one other difference is v1.1.0's fix of the index
manager's project root. These changes do not alter any released measurement.

The original public analysis plan and correction register remain as historical
methodological evidence. Their older commands are superseded by `REPRODUCE.md`.
