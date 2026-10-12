# Recorded environments and dependencies

## Revision campaign rc20261008

Every run's inventory, before and after, is in its run directory under
`campaign/rc20261008/`. This is a summary of what they record.

**Primary host** (phases A, B, C, D and F, and the server of phase E): Intel
Core i7-8550U, four physical cores and eight logical CPUs, Ubuntu 26.04.1 LTS.
The database volume is a SK hynix SC311 SATA SSD. One database service ran at a
time. The database's control group had logical CPUs 0–1, a 3 GB memory ceiling
and no swap; the client ran on logical CPUs 2–3 of the same host over loopback.
Assigning different logical CPUs does not establish separate physical cores.
Database memory targets are 2 GB where applicable; Oracle's SGA and Commercial
System A's configured target are 1.5 GB. Intra-query parallelism is disabled.
Before each run a host check recorded the CPU governor, turbo and SMT state and
the online CPUs.

| Component | Recorded |
|---|---|
| PostgreSQL | 18.6 |
| MySQL | 8.4.11 |
| Oracle | Database 23ai Free 23.7.0.25.01 |
| Commercial System A | withheld |
| Client | Python 3.12.3, Django 6.0.8, SQLAlchemy 2.0.52 |
| Drivers | psycopg2-binary 2.9.12, mysqlclient 2.2.8, oracledb 4.0.2, pyodbc 5.3.0, and Commercial System A's Django backend 1.8.0 |

The transaction runs' inventories did not read the server version; see the
limitations in `campaign/README.md`.

**Separate client** (phase E): an Apple M4 laptop over Wi-Fi to the primary
host, with Python 3.12.15 and the host's package versions. The network record is
in `campaign/rc20261008/E-client/network/`.

**Second server** (phases G and V): the same laptop (Apple M4, 4 performance
and 6 efficiency cores, 16 GB), running each database in a Linux virtual
machine container confined to two virtual CPUs and 3 GB without swap, with the
client in its own container on the other two virtual CPUs and the host's Python
and package versions. Commercial System A's image ran through the operating
system's x86-64 binary translation. The dataset fingerprint was checked before
and after every run.

**Dataset.** TPC-H-derived data generated with DuckDB's `tpch` extension at
scale factors 1 and 2. Each run's records carry the dataset id, a content
fingerprint of the loaded tables (`campaign/rc20261008/evidence/fingerprints/`).

## September 2026 measurements

The first submission described native database services on Ubuntu 24.04 with
the same Intel Core i7-8550U, CPU split, memory ceiling and memory targets.
Its recovered records identify PostgreSQL 18.6, MySQL 8.4.11 and Oracle
Database 23ai Free 23.7.0.25.01. Versions and source commits were not attached
to individual timing rows, so these records describe the likely environment
rather than certify it for every row.

## Dependency files

| File | Use |
|---|---|
| `requirements-analysis.txt` | Exact pins for the offline analysis of both datasets; Python 3.11/3.12 |
| `requirements-dev.txt` | Offline analysis, pytest and Ruff; no database drivers |
| `requirements.txt` | Python 3.12 benchmark runtime, drivers and dataset generator |

The analysis pins describe the environment for rebuilding the released results,
not the environment that measured them. Keep the analysis and benchmark
installations separate. Set connection targets explicitly: defaults in the
source refer to several earlier development setups.
