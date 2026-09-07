#!/usr/bin/env bash
# Drive the TPC-H campaign one query at a time.
#
# Each query runs as its own process and appends its result before the next
# starts, so the campaign survives a hang, a crash or a reboot. Re-running the
# same command skips whatever is already recorded.
#
#   ./scripts/2-benchmark/run_campaign.sh postgresql indexed              # all 22
#   ./scripts/2-benchmark/run_campaign.sh postgresql indexed 8 9 21 22    # just these
#   REPS=9 TIMEOUT=7200 ./scripts/2-benchmark/run_campaign.sh oracle indexed
#
# Environment:
#   REPS     total runs per configuration, first discarded   (default 9)
#   TIMEOUT  server-side statement timeout in seconds        (default 3600)
#   OUTDIR   where the CSVs land      (default results/corrected/measurements)
#
# Set DJANGO_SETTINGS_MODULE, DJ_VENDOR, SA_DSN and TPCH_SF for the target system
# before calling this. The per-system drivers (run_mysql_campaign.sh,
# run_oracle_campaign.sh) do that for you and call this script's logic inline.

set -uo pipefail

# Derived from this script's own location. run_query.py was previously invoked as
# a bare `python3 run_query.py`, which only resolved when the working directory
# happened to be this one.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

DBMS="${1:?usage: run_campaign.sh <dbms> <indexed|non-indexed> [query ...]}"
SCHEMA="${2:?usage: run_campaign.sh <dbms> <indexed|non-indexed> [query ...]}"
shift 2

REPS="${REPS:-9}"
TIMEOUT="${TIMEOUT:-3600}"
OUTDIR="${OUTDIR:-$REPO/results/corrected/measurements}"
OUT="${OUTDIR}/${DBMS}_${SCHEMA//-/_}.csv"

# Scripts import django_app, sqlalchemy_app and tpch_params as top-level packages
# but do not put the repository root on sys.path themselves.
export PYTHONPATH="${PYTHONPATH:-$REPO}"
PYTHON="${PYTHON:-$REPO/venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python3

QUERIES=("$@")
if [ ${#QUERIES[@]} -eq 0 ]; then QUERIES=($(seq 1 22)); fi

mkdir -p "$OUTDIR"
echo "campaign: dbms=$DBMS schema=$SCHEMA reps=$REPS timeout=${TIMEOUT}s"
echo "output:   $OUT"
echo

started=$(date +%s)
ok=0; failed=0; skipped=0

for q in "${QUERIES[@]}"; do
    before=$(wc -l < "$OUT" 2>/dev/null || echo 0)
    "$PYTHON" "$REPO/scripts/2-benchmark/run_query.py" \
        --query "$q" --dbms "$DBMS" --schema "$SCHEMA" \
        --repetitions "$REPS" --timeout "$TIMEOUT" \
        --out "$OUT" --resume
    rc=$?
    after=$(wc -l < "$OUT" 2>/dev/null || echo 0)
    if [ "$before" = "$after" ]; then skipped=$((skipped+1))
    elif [ $rc -eq 0 ]; then ok=$((ok+1))
    else failed=$((failed+1)); echo "  -> Q$q did not complete; recorded and continuing"
    fi
done

elapsed=$(( $(date +%s) - started ))
echo
echo "done in ${elapsed}s: $ok complete, $failed incomplete, $skipped already present"
echo "results: $OUT"
