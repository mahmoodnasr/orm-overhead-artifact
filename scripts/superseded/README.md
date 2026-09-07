# Superseded setup scripts

Kept because `docs/CORRECTIONS.md` refers to several of them as evidence, and
because a reader comparing the paper against the artifact may want to see what
the earlier pipeline looked like. **None of them is part of the reproduction
path**, and several never worked.

Nothing in `scripts/1-setup/`, `scripts/2-benchmark/` or `scripts/4-analysis/`
calls anything here.

## Why each was replaced

| File | Replaced by | Why |
|---|---|---|
| `generate_tpch_data.sh` | `1-setup/generate_tpch_duckdb.py` | built `.tbl` files with `tpch-dbgen`; the pipeline generates once into DuckDB and streams, with no intermediate copy |
| `load_data_*.sh`, `load_*_data.sql` | `1-setup/load_pg.py`, `load_mysql.py`, `load_sqlserver.py`, `load_oracle.py` | all read `.tbl`/`.tbl.clean` files that are no longer produced |
| `setup_oracle*.py`, `setup_oracle_fast.sh` | `1-setup/oracle_groups.py` | predate the working-set approach Oracle Free's 12 GB cap forces |
| `setup_sqlserver_data.{py,sh}` | `1-setup/load_sqlserver.py` | same `.tbl` dependency |
| `generate_tpcc_data.py` | `1-setup/load_tpcc.py` | called `random.randint` with no seed, so every run built a different database and no TPC-C measurement was reproducible even in principle |
| `setup_tpcc_postgres.sh` | `1-setup/load_tpcc.py` | sourced its schema from `scripts/setup/`, a directory that does not exist, and COPYed from `/tpcc-data/*.tbl.clean`, which is neither a mounted path nor a filename anything writes |
| `setup_tpcc_oracle_data.py` | `1-setup/create_tpcc_schema_oracle.sql` + `load_tpcc.py` | embedded the Oracle TPC-C DDL in Python, where it could not be applied on its own; the extracted schema also changes every CHAR to VARCHAR2, which is defect C7 |
