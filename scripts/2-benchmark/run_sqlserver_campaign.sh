#!/usr/bin/env bash
# SQL Server SF10 campaign: validate the 22 queries, then measure them, per schema.
#
# Same shape as run_mysql_campaign.sh. SQL Server Developer edition has no
# database size cap, so the whole schema stays resident and the only staging is
# the secondary indexes in data/indexes/sqlserver_indexes.sql.
#
#   ./scripts/2-benchmark/run_sqlserver_campaign.sh non-indexed
#   ./scripts/2-benchmark/run_sqlserver_campaign.sh indexed
#   ./scripts/2-benchmark/run_sqlserver_campaign.sh indexed 6 14 19   # a subset
#
# Environment:
#   QUERY_TIMEOUT     per-statement ceiling during measurement   (default 900)
#   VALIDATE_TIMEOUT  per-statement ceiling during validation    (default 300)
#   REPS              runs per configuration, first discarded    (default 4)
#   SKIP_VALIDATE     set to 1 to reuse an existing validation log
#
# The database must exist before this runs. The SQL Server image has no
# init-directory mechanism, so docker-compose.yml's mount of setup.sql does
# nothing and the database has to be created explicitly:
#
#   docker compose up -d sqlserver
#   ./scripts/1-setup/init_sqlserver.sh
#   docker exec -i orm-bench-sqlserver /opt/mssql-tools18/bin/sqlcmd \
#       -S localhost -U sa -P "$SQLSERVER_SA_PASSWORD" -C -b -d tpch \
#       < scripts/1-setup/schema_sqlserver.sql
#   python3 scripts/1-setup/load_sqlserver.py

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

SCHEMA="${1:-non-indexed}"
shift 2>/dev/null || true
QUERIES=("$@")
if [ ${#QUERIES[@]} -eq 0 ]; then QUERIES=($(seq 1 22)); fi

# Scale-factor-keyed, so an SF1 campaign cannot append to the completed
# SF10 files: a measurement row's key does not contain the scale factor.
SF="${TPCH_SF:?TPCH_SF must be set - it selects the query parameters (C6) and the results tree}"
if [ "$SF" = "10" ]; then
    RESULTS_ROOT="$REPO/results"
    MEASUREMENTS="$RESULTS_ROOT/corrected/measurements"
else
    RESULTS_ROOT="$REPO/results/sf$SF"
    MEASUREMENTS="$RESULTS_ROOT/measurements"
fi
mkdir -p "$MEASUREMENTS"
OUT="$MEASUREMENTS/sqlserver_${SCHEMA//-/_}.csv"
VALIDATE_LOG="$REPO/results/corrected/sqlserver_${SCHEMA//-/_}.validate.log"
mkdir -p "$MEASUREMENTS"

REPS="${REPS:-4}"
# Read by settings_sqlserver.py as the connection-level query timeout, and by
# run_query.py's set_timeouts, which puts the same ceiling on both raw
# connections. SQL Server has no session-level statement timeout to SET, so
# unlike PostgreSQL and MySQL the bound is client-side on both frameworks.
export QUERY_TIMEOUT="${QUERY_TIMEOUT:-900}"
export VALIDATE_TIMEOUT="${VALIDATE_TIMEOUT:-300}"

export PYTHONPATH="$REPO"

# TPC-H Q11's FRACTION is 0.0001/SF; held at the SF1 constant Q11 returns
# nothing at SF10 while still reporting a plausible time. Defect C6.
export TPCH_SF=10
export DJANGO_SETTINGS_MODULE=settings_sqlserver
export DJ_VENDOR=sqlserver

# The password is URL-encoded: the default contains "!", which is legal in a URL
# but not something to rely on a driver leaving alone.
export SQLSERVER_SA_PASSWORD="${SQLSERVER_SA_PASSWORD:-YourStrong!Passw0rd}"
export SA_DSN="${SA_DSN:-mssql+pyodbc://sa:YourStrong%21Passw0rd@127.0.0.1:1433/tpch?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes}"

PYTHON="${PYTHON:-$REPO/venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python3

echo "SQL Server $SCHEMA campaign"
echo "  repo:    $REPO"
echo "  out:     $OUT"
echo "  reps:    $REPS (first discarded)   timeout: ${QUERY_TIMEOUT}s"
echo

# make_all_results.py folds this into PLAN.md's generated block, so
# "doing right now" is as current as the numbers. Nothing wrote it before,
# which is why that line read "idle" through every campaign.
STATE="$MEASUREMENTS/.campaign_state"
state() { echo "$*" > "$STATE" 2>/dev/null || true; }
trap 'state "idle"' EXIT

# Refuse to measure a system that can answer a repeat without executing
# it. Defect C19: Oracle ran an entire campaign against its result cache,
# and no validation check could see it because a cached result is the
# correct result. Only Oracle has the feature; for the others this records
# why there is nothing to test.
"$PYTHON" "$REPO/scripts/utils/assert_no_result_cache.py" --dbms sqlserver || exit 1

if [ "${SKIP_VALIDATE:-0}" != "1" ]; then
    state "SQL Server $SCHEMA - validating 22 queries"
    echo "############ validating ############"
    "$PYTHON" "$REPO/scripts/validate_queries.py" 2>&1 | tee "$VALIDATE_LOG"
    echo
fi

# Measure only what passed all five checks (C23). The loop below used to run
# over every query whatever the validator printed. On this system the validator
# raises on Django's Q13 (inexpressible, C17) and stops, so SQLAlchemy's Q13 and
# both baselines were never compared - and were measured and reported as
# verified. The gate reads the log just written (or the one reused under
# SKIP_VALIDATE), fails closed on a query with no row, and writes what it
# skipped to ${VALIDATE_LOG%.log}.gate.log. Skipped cells appear in the results
# file as not_run with the validator's verdict as the reason.
PASSED=$("$PYTHON" "$REPO/scripts/utils/validated_queries.py" "$VALIDATE_LOG" \
             --want "${QUERIES[*]}") || true
if [ -z "$PASSED" ]; then
    echo "############ no query passed validation; measuring nothing ############"
else
    echo "############ measuring, validated: Q$PASSED ############"
fi

for n in $PASSED; do
    state "SQL Server $SCHEMA - measuring Q$(printf '%02d' "$n") of 22"
    echo "############ SQL Server $SCHEMA — Q$(printf '%02d' "$n") ############"
    "$PYTHON" "$REPO/scripts/2-benchmark/run_query.py" \
        --query "$n" --dbms sqlserver --schema "$SCHEMA" \
        --repetitions "$REPS" --timeout "$QUERY_TIMEOUT" \
        --out "$OUT" --resume
done

# Rebuild the single results file and the PLAN.md status block from whatever is
# now on disk. Once at the end: it reads every measurement each time, and
# nothing downstream consumes it mid-campaign.
"$PYTHON" "$REPO/scripts/4-analysis/make_all_results.py" \
    --measurements "$MEASUREMENTS" \
    --out "$RESULTS_ROOT/all_results.csv" \
    --scale "$SF"
# --plan is deliberately not passed. It defaults to PLAN.md when building
# SF10 and to nothing otherwise: PLAN.md's generated block describes the
# SF10 grid, and an SF1 rebuild must not silently replace it.

echo "############ SQL Server $SCHEMA finished ############"
