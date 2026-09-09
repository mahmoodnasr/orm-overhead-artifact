# Building a release archive

A release ZIP is built from the checksummed public file list. It excludes Git
history, local outputs, credentials, environments and caches.

```sh
python review.py verify
python review.py reproduce
python -m pytest
python scripts/release.py --output dist/orm-overhead-artifact-v1.1.0.zip
```

The builder verifies input integrity before writing, uses stable archive order,
timestamps and permissions, and creates a `.sha256` sidecar. It refuses to
replace an existing archive. The extracted archive supports the same commands
as the repository checkout.

When intentionally editing release files, update `MANIFEST.json` only after
reviewing the file selection. `python scripts/update_manifest.py` includes Git
tracked and nonignored untracked files, rejects local/private artifacts and
checks the public data contract. It does not publish anything. Re-run the checks
and inspect `git diff` before committing. Preserve the raw public files and their
hash record unless a new measurement campaign is explicitly being released.

The archive includes the complete measurement dataset with Commercial System A
labels. Existing adapters and dependencies still identify the supported database;
see the naming scope in `MANIFEST.md` before distributing the artifact.
