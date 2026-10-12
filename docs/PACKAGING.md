# Building a release archive

A release ZIP is built from the checksummed public file list: the files in
`MANIFEST.json` and, through `campaign/SHA256SUMS`, every file of the campaign
tree. It excludes Git history, local outputs, credentials, environments and
caches.

```sh
python review.py verify
python review.py reproduce
python -m pytest
python scripts/release.py --output dist/orm-overhead-artifact-v2.0.0.zip
```

The builder verifies input integrity before writing, uses stable archive order,
timestamps and permissions, and creates a `.sha256` sidecar. It refuses to
replace an existing archive. The extracted archive supports the same commands
as the repository checkout.

When intentionally editing release files, update `MANIFEST.json` only after
reviewing the file selection. `python scripts/update_manifest.py` includes Git
tracked and nonignored untracked files, rejects local/private artifacts and
checks the public data contract. It records the campaign tree through
`campaign/SHA256SUMS` and `campaign/README.md`; the campaign tree itself is
frozen, and is changed only by releasing a new copy of the campaign record. It does not publish anything. Re-run the checks
and inspect `git diff` before committing. Preserve the raw public files and their
hash record unless a new measurement campaign is explicitly being released.

The archive includes both datasets with Commercial System A labels. The
adapters and dependencies in the source still identify the supported database;
see the naming section of `MANIFEST.md` before distributing the artifact.
