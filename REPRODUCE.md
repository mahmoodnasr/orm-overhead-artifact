# Reproduction guide

## Rebuild the four-system results

Follow the two commands in `README.md`: `review.py verify` checks the package
using the standard library, and `review.py reproduce` rebuilds and compares its
four-system outputs after installing `requirements-analysis.txt`. No database
server, SQL driver, shell environment file or generated dataset is needed.

## Run the source tests

The offline development environment needs no database client libraries:

```sh
python -m pip install -r requirements-dev.txt
TPCH_SF=1 python -m pytest
```

The default collection excludes `test_parameters_take_effect.py`, which needs a
live PostgreSQL database for ORM SQL capture. For a fresh benchmark environment,
use Python 3.12 and install `requirements.txt` separately. MySQL client development
libraries, `pkg-config`, an ODBC driver manager and the selected database driver
must be installed before their compiled Python packages.

After loading the database and configuring the campaign connections, run the
integration check explicitly:

```sh
python tests/test_parameters_take_effect.py
```

These tests check current source behavior; they do not establish equivalence for
historical timings. See `docs/PROTOCOL.md`.

## Prepare a fresh measurement environment

New timings require separately installed database servers and generated data.
Use the recorded host envelope in `docs/ENVIRONMENT.md`. The package does not
install system services, change host CPU settings or supply an exact server image.
Running on other hardware produces a new experiment.

From the package root, copy `.env.example` to `.env`, replace its example
credentials and targets, then load it:

```sh
set -a
. ./.env
set +a
export PYTHONPATH="$PWD"
```

`.env` is shell syntax; it is not loaded automatically by the Python scripts.
Both access paths must use the same database, credentials, driver and isolation
level. The SQLAlchemy URL (`SA_DSN`) must encode special characters in credentials.
`TPCH_SF=1` must match the loaded data; it controls Q11's threshold as well as
the campaign label. Set connection variables explicitly: historical defaults
in the source refer to several different development environments.

| System | Django settings module | SQLAlchemy URL prefix | Loader connection |
|---|---|---|---|
| PostgreSQL | `django_app.settings` | `postgresql+psycopg2://` | `PG_DSN` |
| MySQL | `settings_mysql` | `mysql+mysqldb://` | `MYSQL_*` |
| Oracle | `settings_oracle` | `oracle+oracledb://` | `ORA_USER`, `ORA_PASS`, `ORA_DSN` |
| Commercial System A | `settings_sqlserver` | `mssql+pyodbc://` | `SQLSERVER_*`, `SQLSERVER_SA_PASSWORD` |

For Commercial System A, install the ODBC driver separately and select it in `SA_DSN` and
`SQLSERVER_ODBC_DRIVER`. For Oracle, use matching `ORACLE_*` settings for Django
and `ORA_*` variables for the loader. TPC-C's Oracle loader reads
`ORA_TPCC_USER`, `ORA_TPCC_PASS` and `ORA_DSN`.

## Generate and load TPC-H-derived data

Generation installs DuckDB's `tpch` extension on first use and requires network
access then. Pass the scale and filename explicitly; the historical generator
and loaders default to SF10 filenames.

```sh
python scripts/1-setup/generate_tpch_duckdb.py --sf 1 --out tpch1.duckdb
```

Create a dedicated empty database/schema first. SQL definitions are supplied as
`schema_postgres.sql`, `schema_mysql.sql`, `schema_oracle.sql` and
`schema_sqlserver.sql` under `scripts/1-setup/`. Apply them with the appropriate
database client. The PostgreSQL definition comes from the retained setup
precheck; it is not evidence of every historical server's DDL.

For example, with an empty PostgreSQL `tpch` database and the configured `PG_DSN`:

```sh
psql "$PG_DSN" -v ON_ERROR_STOP=1 -f scripts/1-setup/schema_postgres.sql
python scripts/1-setup/load_pg.py --duckdb tpch1.duckdb
psql "$PG_DSN" -v ON_ERROR_STOP=1 -f data/indexes/postgres_indexes.sql
```

Other systems use `load_mysql.py --duckdb tpch1.duckdb`,
`load_oracle.py --duckdb tpch1.duckdb --sf 1`, or
`load_sqlserver.py --duckdb tpch1.duckdb`. Loaders write to the configured
database. Use an empty database to avoid duplicate records on repeated loads.

Apply the matching file in `data/indexes/` for the indexed configuration. Refresh
optimizer statistics after loading or changing indexes. For the non-indexed
configuration, remove secondary indexes while retaining the schema's key
constraints, then inspect the actual catalog before labeling measurements.
`manage_indexes.py --database default --action drop` supports the default
Django connection; vendor-specific aliases are also available. The `--schema`
measurement option labels a run and does not change database indexes.

## Validate and measure

Set the database-specific `DJANGO_SETTINGS_MODULE`, `DJ_VENDOR` and `SA_DSN`
before running validation. For example, select PostgreSQL in `.env` and validate
Q06 across the eight parameter sets:

```sh
python scripts/validate_queries.py q06 --sets=all
```

The validator saves `validation_results.json` in the current directory. Preserve
that file under a run-specific name after each invocation. Inspect all five
checks and compare the actual results when investigating a failure. The retained
validator has known canonicalization and tolerance limitations; its success is
not a complete equivalence proof.

Measure only after validation and host/index checks. On the recorded Linux CPU
allocation, one analytical query uses:

```sh
mkdir -p results/rerun/measurements
taskset -c 2,3 python scripts/2-benchmark/run_block.py \
  --query 6 --dbms postgresql --schema indexed --blocks 8 --timeout 900 \
  --campaign-id sf1-review-rerun \
  --out results/rerun/measurements/postgresql_indexed.csv
```

Repeat for validated Q01–Q22, each system and each verified index configuration.
Use the statement ceilings recorded in the selected raw input for each campaign;
the example's 900 seconds is not a universal historical ceiling. Preserve warmup,
timeout and error rows. `--resume` skips completed work; use a new output file
for an independent rerun. `run_query.py` retains the earlier unpaired protocol
and is not the SF1 analytical campaign entry point.

## TPC-C-derived transactions

Create a separate empty `tpcc` database (or Oracle `tpcc` schema), apply the matching
`create_tpcc_schema_*.sql`, point **both** framework and loader connections to it,
then run `load_tpcc.py --dbms postgresql` (or the selected vendor). In particular,
update `PG_DSN`, `POSTGRES_DB` and `SA_DSN` for PostgreSQL. These transactions
modify state and must not run against a shared application database.

```sh
python scripts/2-benchmark/run_tpcc.py \
  --transaction 1 --dbms postgresql --schema indexed --repetitions 4 --timeout 900 \
  --out results/rerun/measurements/postgresql_tpcc_indexed.csv
```

Repeat for T1–T5 and each verified configuration. This protocol uses four
repetitions per path, discards the first and exports the remaining median.
It does not use the analytical eight-block design. Throughput is a separate run:

```sh
python scripts/2-benchmark/run_tpcc_throughput.py \
  --dbms postgresql --schema indexed --concurrency 50 --duration 60 --warmup 10 \
  --out results/rerun/measurements/postgresql_tpcc_throughput_indexed.csv
```

## Analyze new measurements

```sh
python scripts/4-analysis/make_all_results.py --scale 1 \
  --measurements results/rerun/measurements --out results/rerun/all_results.csv \
  --validation-logs results/rerun --qerror results/rerun
```

This builds `results/rerun/all_results.csv` from the new runs. The public
`results/sf1/` inputs remain frozen. Never append a new run to those public CSVs. Use `pilot_gate.py` to inspect analytical campaign
variability and recorded ceilings; preserve failing diagnostics. Regenerating
all four systems is always the separate `review.py reproduce` workflow.
