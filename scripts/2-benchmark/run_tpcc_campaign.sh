#!/usr/bin/env bash
# TPC-C campaign: five transactions, four paths each, per schema.
#
#   ./scripts/2-benchmark/run_tpcc_campaign.sh postgresql indexed
#   ./scripts/2-benchmark/run_tpcc_campaign.sh mysql non-indexed
#
# The database must already hold TPC-C data:
#   python3 scripts/1-setup/load_tpcc.py --dbms <vendor>
#
# TPC-C lives in its own database named tpcc, so the TPC-H dataset on the same
# server stays intact and the two benchmarks cannot contend for the same tables.
set -uo pipefail

# The TPC-C database is named by TPCC_* variables, never by the TPC-H ones.
# POSTGRES_DB/MYSQL_DB/SQLSERVER_DB/ORACLE_USER and SA_DSN are all exported by
# campaign-env.sh pointing at the TPC-H database, and reading them here with
# ${VAR:-tpcc} meant an inherited "tpch" won: on 2026-09-05 the PostgreSQL TPC-C
# campaign ran against the TPC-H database, every path failed with
# relation "warehouse" does not exist, and the script still printed "finished".
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

DBMS="${1:-postgresql}"
SCHEMA="${2:-indexed}"

SF="${TPCH_SF:?TPCH_SF must be set - it selects the query parameters (C6) and the results tree}"
if [ "$SF" = "10" ]; then MEAS="$REPO/results/corrected/measurements";
else MEAS="$REPO/results/sf$SF/measurements"; fi
OUT="$MEAS/${DBMS}_tpcc_${SCHEMA//-/_}.csv"
mkdir -p "$MEAS"

export PYTHONPATH="$REPO"
export REPS="${REPS:-4}"
export QUERY_TIMEOUT="${QUERY_TIMEOUT:-900}"

case "$DBMS" in
# Every credential below is ${VAR:-default}, so sourcing campaign-env.sh first
# decides them and this script only fills gaps. They used to be assigned
# unconditionally from the container's values - PostgreSQL on 55432, MySQL as
# root on 33306 - which on a host with natively installed servers overrode a
# correct environment with one that connects to nothing.
postgresql)
    export DJANGO_SETTINGS_MODULE=django_app.settings DJ_VENDOR=postgresql
    export POSTGRES_DB="${TPCC_POSTGRES_DB:-tpcc}"
    export POSTGRES_USER="${POSTGRES_USER:-benchmark}"
    export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-bench}"
    export POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
    export POSTGRES_PORT="${POSTGRES_PORT:-55432}"
    export SA_DSN="${TPCC_SA_DSN:-postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/tpcc}" ;;
mysql)
    export DJANGO_SETTINGS_MODULE=settings_mysql DJ_VENDOR=mysql
    export MYSQL_DB="${TPCC_MYSQL_DB:-tpcc}"
    export MYSQL_USER="${MYSQL_USER:-root}"
    export MYSQL_PASSWORD="${MYSQL_PASSWORD:-bench}"
    export MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
    export MYSQL_PORT="${MYSQL_PORT:-33306}"
    export SA_DSN="${TPCC_SA_DSN:-mysql+mysqldb://${MYSQL_USER}:${MYSQL_PASSWORD}@${MYSQL_HOST}:${MYSQL_PORT}/tpcc}" ;;
sqlserver)
    export DJANGO_SETTINGS_MODULE=settings_sqlserver DJ_VENDOR=sqlserver
    export SQLSERVER_DB="${TPCC_SQLSERVER_DB:-tpcc}"
    export SQLSERVER_USER="${SQLSERVER_USER:-sa}"
    export SQLSERVER_HOST="${SQLSERVER_HOST:-127.0.0.1}"
    export SQLSERVER_PORT="${SQLSERVER_PORT:-1433}"
    export SA_DSN="${TPCC_SA_DSN:-mssql+pyodbc://sa:YourStrong%21Passw0rd@${SQLSERVER_HOST}:${SQLSERVER_PORT}/${SQLSERVER_DB}?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes}" ;;
oracle)
    # Oracle had no branch here at all, so run_tpcc_campaign.sh exited with
    # "unknown dbms: oracle" - which is why Oracle has no TPC-C measurement in
    # any campaign. The four-system TPC-C claim was never reachable by this
    # script; it was three.
    export DJANGO_SETTINGS_MODULE=settings_oracle DJ_VENDOR=oracle
    export ORACLE_USER="${TPCC_ORACLE_USER:-tpcc}"
    export ORACLE_PASSWORD="${ORACLE_PASSWORD:-bench}"
    export ORACLE_HOST="${ORACLE_HOST:-127.0.0.1}"
    export ORACLE_PORT="${ORACLE_PORT:-1521}"
    export ORACLE_SERVICE="${ORACLE_SERVICE:-FREEPDB1}"
    export SA_DSN="${TPCC_SA_DSN:-oracle+oracledb://${ORACLE_USER}:${ORACLE_PASSWORD}@${ORACLE_HOST}:${ORACLE_PORT}/?service_name=${ORACLE_SERVICE}}" ;;
*) echo "unknown dbms: $DBMS" >&2; exit 2 ;;
esac

PYTHON="${PYTHON:-$REPO/venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python3

# See C19; the same guard the TPC-H campaigns run.
"$PYTHON" "$REPO/scripts/utils/assert_no_result_cache.py" --dbms "$DBMS" || exit 1

echo "TPC-C $DBMS $SCHEMA"
echo "  out:  $OUT"
echo "  reps: $REPS (first discarded)"
echo

STATE="$MEAS/.campaign_state"
state() { echo "$*" > "$STATE" 2>/dev/null || true; }
trap 'state "idle"' EXIT

for t in 1 2 3 4 5; do
    state "TPC-C $DBMS $SCHEMA - T$t of 5"
    "$PYTHON" "$REPO/scripts/2-benchmark/run_tpcc.py" \
        --transaction "$t" --dbms "$DBMS" --schema "$SCHEMA" \
        --repetitions "$REPS" --timeout "$QUERY_TIMEOUT" \
        --out "$OUT" --resume
done

"$PYTHON" "$REPO/scripts/utils/count_measurements.py" "$OUT"

# "finished" is not "succeeded". On 2026-09-05 this script ran all five
# transactions against the wrong database, every one of the twenty paths failed
# with relation "warehouse" does not exist, and it printed "finished" and
# returned 0. The chain above it would have carried on to the next
# configuration and left an empty TPC-C column looking complete - the same
# shape as C34, where the analysis reported absence it had caused itself.
#
# TPC-C is 5 transactions x 4 paths = 20 rows per configuration, and every one
# must carry status ok. Anything else stops the run here.
NOK=$("$PYTHON" - "$OUT" <<'PYEOF'
import csv, sys
try:
    rows = [r for r in csv.DictReader(open(sys.argv[1]))]
except OSError:
    print("no-file"); raise SystemExit
ok  = sum(1 for r in rows if r.get("status") == "ok")
bad = [r for r in rows if r.get("status") != "ok"]
print("%d/%d" % (ok, len(rows)))
for r in bad[:3]:
    print("   %s %s/%s %s" % (r.get("query_id"), r.get("framework"),
                              r.get("path"), (r.get("note") or "")[:70]),
          file=sys.stderr)
PYEOF
)
if [ "$NOK" != "20/20" ]; then
    echo
    echo "TPC-C $DBMS $SCHEMA FAILED: $NOK paths ok, expected 20/20" >&2
    exit 1
fi
echo "############ TPC-C $DBMS $SCHEMA finished: $NOK paths ok ############"
