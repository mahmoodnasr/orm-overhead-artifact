# Recorded environment and dependencies

The current manuscript describes native database services on Ubuntu 24.04 with
an Intel Core i7-8550U (four physical cores, eight logical CPUs). One service ran
at a time. Database services used logical CPUs 0–1; the client used 2–3 on the
same host over loopback. This does not establish physical-core isolation. The
retained records do not verify the storage device.

The described cgroup imposed a 3 GB memory ceiling and disabled swap. Database
memory targets were 2 GB, with Oracle's SGA target at 1.5 GB. Intra-query
parallelism was disabled. Record and verify these settings for any new run;
this repository does not provision an exact historical host image.

The recovered records identify PostgreSQL 18.6, MySQL 8.4.11 and Oracle Database
23ai Free 23.7.0.25.01. Versions and source commits were not attached to individual
timing rows, so these records describe the likely campaign environment rather
than certify it for every row.

| Dependency file | Use |
|---|---|
| `requirements-analysis.txt` | Exact direct pins for the offline analysis; Python 3.11/3.12 |
| `requirements-dev.txt` | Offline analysis, pytest and Ruff; no database drivers required |
| `requirements.txt` | Python 3.12 benchmark runtime, drivers and dataset generator |

The benchmark versions are Django 6.0.8 and SQLAlchemy 2.0.52. Each system uses
one shared driver across frameworks: psycopg2 2.9.12, mysqlclient 2.2.8, oracledb
4.0.2 or pyodbc 5.3.0, with mssql-django 1.8.0 where applicable. Native libraries
and database servers are separate prerequisites.

The analysis pins describe the environment for rebuilding the supplied CSVs,
not the environment that measured the historical timings. Keep the analysis
and benchmark installations separate. Set connection targets explicitly:
historical defaults in the source refer to several earlier development setups.
