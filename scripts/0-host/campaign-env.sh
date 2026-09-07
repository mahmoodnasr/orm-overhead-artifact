#!/usr/bin/env bash
# Campaign environment, per engine. Source it, do not execute it:
#
#     source venv/bin/activate
#     source scripts/0-host/campaign-env.sh postgresql
#
# This exists because the environment was previously assembled ad hoc in a
# scratch directory, which is session-scoped: a new session could not run a
# single measurement without reconstructing it from memory. Every value here is
# one that has actually been used to produce committed results.
#
# TPCH_SF is required for correctness, not convenience (C6): Q11's FRACTION is
# 0.0001/SF, and at the wrong scale factor the query returns nothing while still
# scanning, aggregating and sorting - a plausible time for a query that is not
# Q11. run_block.py refuses to start without it.
set -u
ENGINE="${1:?usage: source campaign-env.sh <postgresql|mysql|sqlserver|oracle> [tpch|tpcc]}"
DB_KIND="${2:-tpch}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$REPO"
export TPCH_SF=1
export VALIDATE_TIMEOUT=300

case "$ENGINE" in
  postgresql)
    export DJANGO_SETTINGS_MODULE=django_app.settings
    export DJ_VENDOR=postgresql
    export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432
    export POSTGRES_USER=benchmark POSTGRES_PASSWORD=benchmark_pass
    # The port is the easy one to get wrong: django_app/settings.py still
    # defaults to 55432 from the container era, and a wrong port does not
    # announce itself - the run prints a table with MATCH and SQL= reading n/a,
    # which looks like a partial result and is a harness that never connected.
    export POSTGRES_DB="$([ "$DB_KIND" = tpcc ] && echo tpcc || echo tpch)"
    export SA_DSN="postgresql+psycopg2://benchmark:benchmark_pass@127.0.0.1:5432/${POSTGRES_DB}"
    ;;
  mysql)
    export DJANGO_SETTINGS_MODULE=settings_mysql
    export DJ_VENDOR=mysql
    export MYSQL_HOST=127.0.0.1 MYSQL_PORT=3306
    export MYSQL_USER=benchmark MYSQL_PASSWORD=benchmark_pass
    export MYSQL_DB="$([ "$DB_KIND" = tpcc ] && echo tpcc || echo tpch)"
    # mysqldb, never pymysql. Django uses mysqlclient, and the plan makes
    # driver parity a first-class measurement requirement: a compiled driver
    # under one framework and a pure-Python one under the other could move the
    # framework contrast by more than the effects this study reports. Verified
    # in use: both frameworks report MySQLdb 2.2.8.
    export SA_DSN="mysql+mysqldb://benchmark:benchmark_pass@127.0.0.1:3306/${MYSQL_DB}"
    ;;
  sqlserver)
    export DJANGO_SETTINGS_MODULE=settings_sqlserver
    export DJ_VENDOR=sqlserver
    export SQLSERVER_HOST=127.0.0.1 SQLSERVER_PORT=1433
    export SQLSERVER_DB="$([ "$DB_KIND" = tpcc ] && echo tpcc || echo tpch)"
    export SQLSERVER_USER=sa
    # The value scripts/1-setup/init_sqlserver.sh has always fallen back to, and
    # the one this host's instance actually accepts. It is written here rather
    # than left to be remembered because "credentials are not stored here" cost
    # a session: the note said set three variables and named no values, so the
    # campaign could not start until the password was recovered by trying it.
    export SQLSERVER_PASSWORD="${SQLSERVER_PASSWORD:-YourStrong!Passw0rd}"
    export SQLSERVER_SA_PASSWORD="$SQLSERVER_PASSWORD"
    # Driver 18 is what is installed; it defaults to Encrypt=yes, so
    # TrustServerCertificate is required against a self-signed instance.
    export SA_DSN="mssql+pyodbc://sa:YourStrong%21Passw0rd@127.0.0.1:1433/${SQLSERVER_DB}?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
    ;;
  oracle)
    export DJANGO_SETTINGS_MODULE=settings_oracle
    export DJ_VENDOR=oracle
    export ORACLE_HOST=127.0.0.1 ORACLE_PORT=1521 ORACLE_SERVICE=FREEPDB1
    echo "note: Oracle credentials are not stored here; set ORACLE_USER," >&2
    echo "      ORACLE_PASSWORD and SA_DSN before measuring." >&2
    ;;
  *)
    echo "unknown engine: $ENGINE" >&2
    ;;
esac

echo "environment: $ENGINE / $DB_KIND, scale factor $TPCH_SF"
echo "reminder: run the client under 'taskset -c 2,3'; run_block.py refuses otherwise,"
echo "          and do not touch the machine while a run is in flight."
