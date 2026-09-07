#!/usr/bin/env bash
# Oracle SF10 campaign, driven by working sets.
#
# For each group: bring the resident tables to what the group needs, validate the
# group's queries against the five checks, then measure them. Validation runs
# first and its output is kept — a group whose queries do not agree across the
# four paths must not contribute timings.
#
# The groups are ordered so the resident table set only grows, which loads
# LINEITEM once rather than seventeen times. Oracle Free caps user data at 12 GB
# and SF10 occupies 10.81 GB, so the data fits and its indexes do not; see
# oracle_groups.py, which prints the group table from the code that enforces it.
#
#   ./scripts/2-benchmark/run_oracle_campaign.sh non-indexed          # every group
#   ./scripts/2-benchmark/run_oracle_campaign.sh non-indexed C D E    # named groups
#
# Environment:
#   QUERY_TIMEOUT  server-side statement timeout, seconds  (default 900)
#   REPS           runs per configuration, first discarded (default 4)
#
# Paths are derived from this script's own location. They were previously
# absolute paths into /home/claude/bench, the sandbox the original campaign ran
# in, so nothing here ran from a clone.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

SCHEMA="${1:-non-indexed}"
shift 2>/dev/null || true
if [ "$#" -gt 0 ]; then GROUP_LIST="$*"; else GROUP_LIST="A B C D E F G"; fi

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
OUT="$MEASUREMENTS/oracle_${SCHEMA//-/_}.csv"
LOGDIR="$REPO/results/corrected/logs"
mkdir -p "$MEASUREMENTS" "$LOGDIR"

REPS="${REPS:-4}"
# One ceiling for both stages. A query that cannot finish inside it during
# validation will not finish inside it during measurement either, and matching
# the two means a timeout row and a validation failure say the same thing. Four
# access paths at the ceiling is 60 minutes for a query that cannot run at all,
# which is the price of recording that fact rather than omitting it.
export QUERY_TIMEOUT="${QUERY_TIMEOUT:-900}"
export VALIDATE_TIMEOUT="$QUERY_TIMEOUT"

# Scripts import django_app, sqlalchemy_app and tpch_params as top-level
# packages but do not put the repository root on sys.path themselves.
export PYTHONPATH="$REPO"

# Q11's FRACTION is 0.0001/SF, not a constant.
export TPCH_SF=10
export DJANGO_SETTINGS_MODULE=settings_oracle
export DJ_VENDOR=oracle
export SA_DSN="${SA_DSN:-oracle+oracledb://tpch:bench@127.0.0.1:41521/?service_name=FREEPDB1}"

PYTHON="${PYTHON:-$REPO/venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python3

queries_for() {
    case "$1" in
        A) echo "2 11 13 16 22" ;;
        B) echo "1 6 15" ;;
        C) echo "14 17 19" ;;
        D) echo "4 12" ;;
        E) echo "3 10 18" ;;
        F) echo "5 7 8 21" ;;
        G) echo "9 20" ;;
        *) echo "" ;;
    esac
}

for grp in $GROUP_LIST; do
    qnums=$(queries_for "$grp")
    if [ -z "$qnums" ]; then
        echo "unknown group $grp, skipping"
        continue
    fi
    echo "############ group $grp ($SCHEMA): Q$qnums ############"

    "$PYTHON" "$REPO/scripts/1-setup/oracle_groups.py" --group "$grp" --schema "$SCHEMA" \
        2>&1 | tee "$LOGDIR/oracle_grp_${grp}_${SCHEMA}.setup.log"

    tags=""
    for n in $qnums; do tags="$tags q$(printf '%02d' "$n")"; done
    # shellcheck disable=SC2086
    VLOG="$LOGDIR/oracle_grp_${grp}_${SCHEMA}.validate.log"
    "$PYTHON" "$REPO/scripts/validate_queries.py" $tags \
        2>&1 | tee "$VLOG"

    # The header of this file says a group whose queries do not agree across the
    # four paths "must not contribute timings". It did: group F's Q08 failed
    # MATCH and ORM=SQL - Django's result differed from both baselines - and was
    # measured in the next line and reported as -0.6%. Defect C23. The gate
    # reads the group's validation log, keeps only what passed all five checks,
    # fails closed on a query with no row, and records the rest in
    # ${VLOG%.log}.gate.log; skipped cells show in the results file as not_run
    # with the validator's verdict.
    PASSED=$("$PYTHON" "$REPO/scripts/utils/validated_queries.py" "$VLOG" \
                 --want "$qnums") || true
    if [ -z "$PASSED" ]; then
        echo "############ group $grp: no query passed validation; measuring nothing ############"
    else
        echo "############ group $grp: measuring, validated: Q$PASSED ############"
    fi

    for n in $PASSED; do
        "$PYTHON" "$REPO/scripts/2-benchmark/run_query.py" \
            --query "$n" --dbms oracle --schema "$SCHEMA" \
            --repetitions "$REPS" --timeout "$QUERY_TIMEOUT" --out "$OUT" --resume \
            2>&1 | grep -E "^  (django|sqlalchemy)|appended|=== "
    done
done

# Rebuild the single results file and the PLAN.md status block from whatever is
# now on disk.
"$PYTHON" "$REPO/scripts/4-analysis/make_all_results.py" \
    --measurements "$MEASUREMENTS" \
    --out "$RESULTS_ROOT/all_results.csv" \
    --scale "$SF"
# --plan is deliberately not passed. It defaults to PLAN.md when building
# SF10 and to nothing otherwise: PLAN.md's generated block describes the
# SF10 grid, and an SF1 rebuild must not silently replace it. | head -3

echo "############ Oracle campaign finished ($SCHEMA) ############"
