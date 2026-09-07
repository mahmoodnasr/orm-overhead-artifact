#!/usr/bin/env bash
# MySQL SF10 campaign: validate the 22 queries, then measure them, per schema.
#
# No working-set grouping here — MySQL has no edition size cap, so the whole
# schema stays resident and the only staging is the secondary indexes.
#
#   ./scripts/2-benchmark/run_mysql_campaign.sh non-indexed
#   ./scripts/2-benchmark/run_mysql_campaign.sh indexed
#   ./scripts/2-benchmark/run_mysql_campaign.sh indexed 6 14 19   # a subset
#
# Environment:
#   QUERY_TIMEOUT     server-side statement timeout, seconds   (default 900)
#   VALIDATE_TIMEOUT  per-statement ceiling during validation  (default 300)
#   REPS              runs per configuration, first discarded  (default 4)
#   SKIP_VALIDATE     set to 1 to reuse an existing validation log
#
# Paths are derived from this script's own location. They were previously
# absolute paths into /home/claude/bench, the sandbox the original campaign ran
# in, so nothing here ran from a clone.

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
OUT="$MEASUREMENTS/mysql_${SCHEMA//-/_}.csv"
VALIDATE_LOG="$REPO/results/corrected/mysql_${SCHEMA//-/_}.validate.log"
mkdir -p "$MEASUREMENTS"

REPS="${REPS:-4}"
export QUERY_TIMEOUT="${QUERY_TIMEOUT:-900}"
# Validation gets a shorter ceiling than measurement on purpose. Its job is to
# catch wrong answers, not to characterise slow ones, and at SF10 a handful of
# TPC-H queries cannot finish without indexes in any framework. A query that
# only fails validation on the clock is recorded as such rather than treated as
# a wrong answer.
export VALIDATE_TIMEOUT="${VALIDATE_TIMEOUT:-300}"

# Scripts import django_app, sqlalchemy_app and tpch_params as top-level
# packages but do not put the repository root on sys.path themselves.
export PYTHONPATH="$REPO"

# Every campaign needs this. TPC-H Q11's FRACTION is 0.0001/SF, and held at the
# SF1 constant Q11 returns nothing at SF10 while still reporting a plausible
# time.
export TPCH_SF=10
export DJANGO_SETTINGS_MODULE=settings_mysql
export DJ_VENDOR=mysql
export SA_DSN="${SA_DSN:-mysql+mysqldb://root:bench@127.0.0.1:33306/tpch}"

PYTHON="${PYTHON:-$REPO/venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python3

echo "MySQL $SCHEMA campaign"
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
"$PYTHON" "$REPO/scripts/utils/assert_no_result_cache.py" --dbms mysql || exit 1

if [ "${SKIP_VALIDATE:-0}" != "1" ]; then
    state "MySQL $SCHEMA - validating 22 queries"
    echo "############ validating ############"
    "$PYTHON" "$REPO/scripts/validate_queries.py" 2>&1 | tee "$VALIDATE_LOG"
    echo
fi

# Measure only what passed all five checks (C23). The comment on
# VALIDATE_TIMEOUT above says a query that fails only on the clock "is recorded
# as such" - and until this gate existed nothing recorded it: the loop ran over
# every query regardless, and the results file's validation columns came from an
# SF1 log (C22). The gate reads the log just written (or the one reused under
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
    state "MySQL $SCHEMA - measuring Q$(printf '%02d' "$n") of 22"
    echo "############ MySQL $SCHEMA — Q$(printf '%02d' "$n") ############"
    "$PYTHON" "$REPO/scripts/2-benchmark/run_query.py" \
        --query "$n" --dbms mysql --schema "$SCHEMA" \
        --repetitions "$REPS" --timeout "$QUERY_TIMEOUT" \
        --out "$OUT" --resume
done

# Rebuild the single results file and the PLAN.md status block from whatever is
# now on disk. Done once at the end rather than after every query: it reads all
# the measurements each time, and nothing downstream consumes it mid-campaign.
"$PYTHON" "$REPO/scripts/4-analysis/make_all_results.py" \
    --measurements "$MEASUREMENTS" \
    --out "$RESULTS_ROOT/all_results.csv" \
    --scale "$SF"
# --plan is deliberately not passed. It defaults to PLAN.md when building
# SF10 and to nothing otherwise: PLAN.md's generated block describes the
# SF10 grid, and an SF1 rebuild must not silently replace it.

echo "############ MySQL $SCHEMA finished ############"
