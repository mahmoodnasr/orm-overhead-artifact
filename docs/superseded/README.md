# Superseded documentation

These describe the earlier pipeline: `tpch-dbgen` producing `.tbl` files,
`load_data_*.sh` reading them, and `setup_reproducibility.sh` orchestrating it.
That pipeline no longer exists — data generation moved to DuckDB and the loaders
stream — so following any of these leads to a step that fails.

They are kept rather than deleted because the paper refers to several of them by
name, and because `docs/CORRECTIONS.md` cites what they claimed as evidence of
what was believed at the time.

**Current documentation:**

| | |
|---|---|
| `REPRODUCE.md` (repository root) | the path that was actually used |
| `docs/CORRECTIONS.md` | the twenty defects |
| `docs/LIMITATIONS.md` | what the results do and do not support |
| `docs/ENVIRONMENT.md` | what each system was given and ran on |
| `docs/PARALLELISM.md` | why MySQL runs every query on one thread |
| `PLAN.md` | the living execution plan |
