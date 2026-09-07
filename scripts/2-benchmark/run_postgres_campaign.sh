#!/usr/bin/env bash
# PostgreSQL SF10 campaign: validate the 22 queries, then measure them, per schema.
#
# Same shape as run_mysql_campaign.sh and run_sqlserver_campaign.sh. There was no
# PostgreSQL equivalent: the original campaign ran in a sandbox from ad-hoc
# commands, which is part of why its configuration could not be reconstructed
# later.
#
#   ./scripts/2-benchmark/run_postgres_campaign.sh non-indexed
#   ./scripts/2-benchmark/run_postgres_campaign.sh indexed
#   ./scripts/2-benchmark/run_postgres_campaign.sh indexed 6 14 19   # a subset
#
# Environment:
#   QUERY_TIMEOUT     server-side statement_timeout, seconds     (default 900)
#   VALIDATE_TIMEOUT  per-statement ceiling during validation    (default 300)
#   REPS              runs per configuration, first discarded    (default 4)
#   SKIP_VALIDATE     set to 1 to reuse an existing validation log
#
# The connection settings below are explicit rather than defaulted, because four
# files in this repository disagree about PostgreSQL's port and two disagree
# about the user. docker-compose.yml publishes ${POSTGRES_PORT:-55432}, .env sets
# 55432, django_app/settings.py defaults to 55432 and user "benchmark", and
# scripts/1-setup/load_pg.py's fallback DSN says user "postgres". Only the
# combination below actually connects.

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
OUT="$MEASUREMENTS/postgresql_${SCHEMA//-/_}.csv"
VALIDATE_LOG="$REPO/results/corrected/postgresql_${SCHEMA//-/_}.validate.log"
mkdir -p "$MEASUREMENTS"

REPS="${REPS:-4}"
export QUERY_TIMEOUT="${QUERY_TIMEOUT:-900}"
export VALIDATE_TIMEOUT="${VALIDATE_TIMEOUT:-300}"

export PYTHONPATH="$REPO"

# TPC-H Q11's FRACTION is 0.0001/SF; held at the SF1 constant Q11 returns nothing
# at SF10 while still reporting a plausible time. Defect C6.
export TPCH_SF=10
export DJANGO_SETTINGS_MODULE=django_app.settings
export DJ_VENDOR=postgresql

export POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
export POSTGRES_PORT="${POSTGRES_PORT:-55432}"
export POSTGRES_DB="${POSTGRES_DB:-tpch}"
export POSTGRES_USER="${POSTGRES_USER:-benchmark}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-bench}"

export PG_DSN="${PG_DSN:-host=$POSTGRES_HOST port=$POSTGRES_PORT dbname=$POSTGRES_DB user=$POSTGRES_USER password=$POSTGRES_PASSWORD}"
export SA_DSN="${SA_DSN:-postgresql+psycopg2://$POSTGRES_USER:$POSTGRES_PASSWORD@$POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB}"

PYTHON="${PYTHON:-$REPO/venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python3

echo "PostgreSQL $SCHEMA campaign"
echo "  repo:    $REPO"
echo "  out:     $OUT"
echo "  reps:    $REPS (first discarded)   timeout: ${QUERY_TIMEOUT}s"
echo "  target:  $POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB as $POSTGRES_USER"
echo

# Record the parallelism actually in force. This campaign exists because the
# original ran at PostgreSQL's default of 2 workers per gather while SQL Server
# ran at 8; asserting the new setting is not the same as checking it.
echo "############ parallelism in force ############"
PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
    "SELECT name, setting FROM pg_settings
      WHERE name IN ('max_parallel_workers_per_gather','max_parallel_workers',
                     'max_worker_processes','shared_buffers','work_mem');" 2>&1 \
  || echo "  (psql not on PATH; skipping - the campaign does not depend on this)"
echo

# Refuse to measure a system that can answer a repeat without executing
# it. Defect C19: Oracle ran an entire campaign against its result cache,
# and no validation check could see it because a cached result is the
# correct result. Only Oracle has the feature; for the others this records
# why there is nothing to test.
"$PYTHON" "$REPO/scripts/utils/assert_no_result_cache.py" --dbms postgresql || exit 1

if [ "${SKIP_VALIDATE:-0}" != "1" ]; then
    echo "############ validating ############"
    "$PYTHON" "$REPO/scripts/validate_queries.py" 2>&1 | tee "$VALIDATE_LOG"
    echo
fi

# Measure only what passed all five checks. Defect C23: this loop ran over every
# query in the list whatever the validator had just printed, so Q18 - which timed
# out on the validator's clock in both schemas - was timed and reported as if
# verified. The gate reads the log just written (or the one reused under
# SKIP_VALIDATE) and fails closed: a query with no row in it is not measured.
# What was skipped, and why, is in ${VALIDATE_LOG%.log}.gate.log, and the
# results file shows those cells as not_run with the validator's verdict.
PASSED=$("$PYTHON" "$REPO/scripts/utils/validated_queries.py" "$VALIDATE_LOG" \
             --want "${QUERIES[*]}") || true
if [ -z "$PASSED" ]; then
    echo "############ no query passed validation; measuring nothing ############"
else
    echo "############ measuring, validated: Q$PASSED ############"
fi

for n in $PASSED; do
    echo "############ PostgreSQL $SCHEMA — Q$(printf '%02d' "$n") ############"
    "$PYTHON" "$REPO/scripts/2-benchmark/run_query.py" \
        --query "$n" --dbms postgresql --schema "$SCHEMA" \
        --repetitions "$REPS" --timeout "$QUERY_TIMEOUT" \
        --out "$OUT" --resume
done

"$PYTHON" "$REPO/scripts/4-analysis/make_all_results.py" \
    --measurements "$MEASUREMENTS" \
    --out "$RESULTS_ROOT/all_results.csv" \
    --scale "$SF"
# --plan is deliberately not passed. It defaults to PLAN.md when building
# SF10 and to nothing otherwise: PLAN.md's generated block describes the
# SF10 grid, and an SF1 rebuild must not silently replace it.

echo "############ PostgreSQL $SCHEMA finished ############"
