#!/usr/bin/env bash
# Phase 6 pilot: the runtime and noise pilot from SF1_RERUN_PLAN.md section 3.
#
# Six queries, chosen by known behaviour rather than by complexity band:
#
#   Q06  one very fast query - the floor, where framework cost dominates
#   Q02  parameterisation sensitivity - eight sets move its selectivity most
#   Q15  multiple statements in one path
#   Q16  historical instability - moved 82 points between the SF10 campaigns
#   Q17  the rewrite, and a censoring candidate non-indexed
#   Q21  one heavy query
#
# Both schema configurations, full eight-block protocol. What it produces:
# the SF1 CV distribution, per-query runtimes, the timeout margins, and the
# replication count for the microbenchmark. What it is judged against is
# ANALYSIS_PLAN.md section 8 - thresholds written BEFORE this runs, so the
# pilot can fail.
#
# The two configurations cannot coexist: non-indexed means the indexes are
# dropped, so this script does one configuration per invocation and says which.
#
# Usage:
#   scripts/2-benchmark/run_pilot.sh postgresql indexed
#   scripts/2-benchmark/run_pilot.sh oracle non-indexed
set -euo pipefail

DBMS="${1:?usage: run_pilot.sh <dbms> <indexed|non-indexed> [pilot|campaign]}"
SCHEMA="${2:?usage: run_pilot.sh <dbms> <indexed|non-indexed> [pilot|campaign]}"
MODE="${3:-pilot}"

# pilot   six queries chosen by known behaviour, written to results/sf1/pilot/
# campaign all 22, written to results/sf1/measurements/ - the same protocol,
#         the same gates, a different query list and a different destination.
# The destination follows TPCH_SF, like every other results path in the repo
# (scripts/utils/results_paths.py). It used to be the literal string
# "results/sf1/measurements", which meant a shakedown at SF0.01 would have
# written its throwaway rows straight into the SF1 campaign directory - the
# exact silent-overwrite that results_paths.py exists to prevent, reintroduced
# one level up.
: "${TPCH_SF:?TPCH_SF must be set - it selects the query parameters (C6) and the results tree}"
if [ "$TPCH_SF" = "10" ]; then SFDIR="results/corrected"; else SFDIR="results/sf${TPCH_SF}"; fi
if [ "$MODE" = campaign ]; then
    QUERIES="${TPCH_QUERIES:-$(seq 1 22)}"
    DEST="$SFDIR/measurements"
else
    QUERIES="${PILOT_QUERIES:-6 2 15 16 17 21}"
    DEST="$SFDIR/pilot"
fi
CLIENT_CPUS="${BENCH_CLIENT_CPUS:-2,3}"
OUT="$DEST/${DBMS}_${SCHEMA//-/_}.csv"
LOG="$DEST/${DBMS}_${SCHEMA//-/_}.log"

cd "$(dirname "$0")/../.."
mkdir -p "$(dirname "$OUT")"

# The gate, not a reminder. On 2026-09-02 a second engine was live inside the
# envelope for 16 minutes of a 68-minute run and only the journal revealed it
# afterwards; the run's pass/fail survived and its timings did not. A pilot
# whose whole output is timings cannot afford that, so it refuses to start.
# BENCH_SHAKEDOWN=1 lifts the one-engine-at-a-time rule so all four can be
# validated concurrently. It is only ever correct for a coverage run: with four
# engines and four clients sharing four cores, every number produced is
# contended and none of it is a measurement. The campaign_id carries
# "shakedown" so such a file can never be mistaken for one later, and the noise
# and ceiling sections of the gate are meaningless on it by construction.
echo "=== host check ==="
if [ "${BENCH_SHAKEDOWN:-0}" = "1" ]; then
    echo "  SHAKEDOWN: host envelope NOT enforced, other engines may be live."
    echo "  Coverage only - the timings in this file are contended and invalid."
elif ! sudo bench-host verify "$DBMS"; then
    echo
    echo "REFUSING TO RUN: the host is not campaign-ready (see the marked lines)."
    echo "Fix it with:  sudo bench-host apply $DBMS"
    echo "None of it survives a reboot, so this is expected after one."
    exit 1
fi

echo
echo "=== $MODE: $DBMS $SCHEMA ==="
echo "    queries: $(echo $QUERIES | tr '\n' ' ')"
echo "    output: $OUT"
echo "    client pinned to cores $CLIENT_CPUS; the engine has its own"
echo

# The schema label is written onto every raw row and nothing used to check
# that the database agreed with it. A run against a database whose indexes were
# never dropped produces rows labelled non-indexed and measured indexed, and
# indexed-versus-non-indexed is one of the three primary contrasts. No timing
# would reveal it: a fast query is exactly what "indexed" predicts.
DB_ALIAS="$DBMS"
[ "$DBMS" = "postgresql" ] && DB_ALIAS="default"
if ! python3 scripts/1-setup/manage_indexes.py \
        --database "$DB_ALIAS" --action verify --expect "$SCHEMA"; then
    echo
    echo "REFUSING TO RUN: the database's index state does not match '$SCHEMA'."
    echo "Put it in the right configuration first:"
    echo "    python3 scripts/1-setup/manage_indexes.py --database $DB_ALIAS \\"
    echo "        --action $([ "$SCHEMA" = indexed ] && echo create || echo drop)"
    exit 1
fi

# Statistics, before any timing, every time. This used to happen only inside
# manage_indexes.py --action create, so a database that arrived already in the
# right configuration was measured with whatever statistics it happened to
# carry. SQL Server's first campaign is what that costs: with auto_create_stats
# on, the optimiser built them during the run, and Q19's django/orm path went
# from ~6.1 s for six blocks to 0.29 s at block 7 and stayed there. Re-running
# that cell afterwards gave 0.18-0.28 s on all four paths. Four minutes here
# buys a system that is not still adapting to the measurement.
echo
echo "=== statistics ==="
if ! python3 scripts/1-setup/manage_indexes.py \
        --database "$DB_ALIAS" --action analyze; then
    echo
    echo "REFUSING TO RUN: the optimiser's statistics could not be rebuilt."
    exit 1
fi

for q in $QUERIES; do
    taskset -c "$CLIENT_CPUS" python3 scripts/2-benchmark/run_block.py \
        --query "$q" --dbms "$DBMS" --schema "$SCHEMA" \
        --timeout "${PILOT_TIMEOUT:-900}" \
        --campaign-id "${BENCH_SHAKEDOWN:+shakedown-}${MODE}-sf${TPCH_SF}" \
        --out "$OUT" --resume 2>&1 | tee -a "$LOG"
done

echo
echo "=== $MODE complete: $OUT ==="
echo "Judge it against ANALYSIS_PLAN.md section 8 with:"
echo "    python3 scripts/4-analysis/pilot_gate.py $OUT"
