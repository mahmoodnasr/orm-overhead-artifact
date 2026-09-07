# Reproducing this study

The path that was actually used. Every command here was run to produce
`results/all_results.csv`; nothing is reconstructed from memory.

An earlier pipeline generated the dataset with `tpch-dbgen` as `.tbl` files.
It no longer exists; generation moved to DuckDB and the loaders stream from it.
Use this file rather than anything in `docs/guides/` for steps you intend to run.

## What you need

Docker, Python 3.11, and about 60 GB of disk. The venv pins Django 4.2 and
SQLAlchemy 2.0.23; `requirements.txt` has the rest.

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=.
export TPCH_SF=10          # required: TPC-H Q11's threshold is 0.0001/SF, not
                           # a constant, and at the SF1 value Q11 returns
                           # nothing at SF10 while still reporting a plausible
                           # time. Defect C6.
```

## 1. Generate the dataset, once

```bash
python3 scripts/1-setup/generate_tpch_duckdb.py        # SF10, ~2 min, 2.5 GB
```

Every loader streams from this file. DuckDB's `tpch` extension generates from a
fixed generator, so the same scale factor gives the same rows on any machine.
The script checks the lineitem count rather than trusting that it ran.

## 2. Bring up one database at a time

One, not four. On a 16 GB machine two resident SF10 datasets contend for the
page cache and neither set of timings is reproducible.

```bash
docker compose up -d postgresql      # or mysql, sqlserver, oracle
```

## 3. Load, index, measure

Each campaign script validates before it measures and refuses to start if the
system can answer a repeated query from a result cache (defect C19).

### PostgreSQL

```bash
python3 scripts/1-setup/load_pg.py
./scripts/2-benchmark/run_postgres_campaign.sh non-indexed
docker exec -i orm-bench-postgresql psql -U benchmark -d tpch < data/indexes/postgres_indexes.sql
./scripts/2-benchmark/run_postgres_campaign.sh indexed
```

### MySQL

```bash
docker exec -i orm-bench-mysql mysql -uroot -pbench < scripts/1-setup/schema_mysql.sql
python3 scripts/1-setup/load_mysql.py
./scripts/2-benchmark/run_mysql_campaign.sh non-indexed
docker exec -i orm-bench-mysql mysql -uroot -pbench tpch < data/indexes/mysql_indexes.sql
./scripts/2-benchmark/run_mysql_campaign.sh indexed
```

### SQL Server

The image has no init-directory mechanism, so the database must be created
explicitly — `docker-compose.yml` mounts `setup.sql` where the image ignores it
(defect C12).

```bash
./scripts/1-setup/init_sqlserver.sh
docker exec -i orm-bench-sqlserver /opt/mssql-tools18/bin/sqlcmd \
    -S localhost -U sa -P "$SQLSERVER_SA_PASSWORD" -C -b -d tpch \
    < scripts/1-setup/schema_sqlserver.sql
python3 scripts/1-setup/load_sqlserver.py
./scripts/2-benchmark/run_sqlserver_campaign.sh non-indexed
```

### Oracle

Oracle Database Free is licence-limited to 2 CPU threads, 2 GB RAM and 12 GB of
user data, so the dataset fits and its indexes do not. Queries are measured per
working set — only the tables a group references are held resident.

```bash
python3 scripts/1-setup/oracle_groups.py --list
python3 scripts/1-setup/oracle_groups.py --group A --schema non-indexed
python3 scripts/2-benchmark/run_query.py --query 2 --dbms oracle \
    --schema non-indexed --repetitions 4 --timeout 900 \
    --out results/corrected/measurements/oracle_non_indexed.csv --resume
```

Group G (Q09, Q20) does not fit at all: its working set reaches 12.37 GB and
raises ORA-12954.

## 4. TPC-C

```bash
python3 scripts/1-setup/load_tpcc.py --dbms postgresql          # seeded, 4.9M rows
./scripts/2-benchmark/run_tpcc_campaign.sh postgresql indexed   # latency
python3 scripts/2-benchmark/run_tpcc_throughput.py \
    --dbms postgresql --schema indexed --concurrency 50 --duration 60 \
    --out results/corrected/measurements/tpcc_throughput.csv    # QPM
```

Latency goes in the 432-row grid; throughput is a separate file because the grid
has no column for concurrency. They answer different questions and are not
interchangeable.

## 5. Rebuild the results file and the analysis

```bash
python3 scripts/4-analysis/make_all_results.py     # writes results/all_results.csv
python3 scripts/4-analysis/analyze_all.py          # cross-system tables
```

`results/all_results.csv` is generated and never hand-edited. It always carries
all 432 rows; a cell that was not measured says why in `status_note`.

## What to read first

| | |
|---|---|
| `docs/ENVIRONMENT.md` | what each system was given and what it actually ran on |
| `docs/PARALLELISM.md` | why MySQL runs every query on one thread |
| `docs/README.md` | index of the remaining documentation |
