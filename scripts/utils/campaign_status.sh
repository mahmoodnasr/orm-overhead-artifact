#!/usr/bin/env bash
# What the campaign is doing right now.
#
# The campaign runs detached for many hours, so the question "is it stuck or is
# this query just slow?" comes up constantly. Answering it needs two things that
# live in different places: what the harness thinks it is doing (the logs) and
# what the server is actually executing (the process list). This prints both.
#
#   ./scripts/utils/campaign_status.sh                       whichever campaign is live
#   ./scripts/utils/campaign_status.sh sqlserver non-indexed  a named one
#   ./scripts/utils/campaign_status.sh -w                     refresh every 20s
#
# A query is progressing, not hung, if `time` climbs and CPU is non-zero.
#
# The DBMS and schema used to be hardcoded to mysql_indexed, which meant the
# script silently reported the previous campaign's numbers once MySQL was done.
# With no arguments it now picks whichever campaign log was written to most
# recently, and prints which one it chose.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CORR="$REPO/results/corrected"

WATCH=0
[ "${1:-}" = "-w" ] && { WATCH=1; shift; }

DBMS="${1:-}"
SCHEMA="${2:-}"

resolve() {
    # Explicit arguments win; otherwise take the most recently touched campaign
    # log, so "what is running now" needs no arguments.
    if [ -n "$DBMS" ] && [ -n "$SCHEMA" ]; then
        TAG="${DBMS}_${SCHEMA//-/_}"
        return
    fi
    # Key on the measurements file that was written to most recently, not on
    # the campaign log. Not every campaign has a log: the Oracle working-set
    # chain drives run_query.py directly, so it writes measurements but no
    # <tag>.campaign.log, and keying on the log reported whichever campaign
    # finished last - it showed "postgresql_indexed" while Oracle was measuring.
    # Every campaign writes measurements, so that is the reliable signal.
    local newest
    newest=$(ls -t "$CORR"/measurements/*.csv 2>/dev/null | head -1)
    if [ -z "$newest" ]; then
        newest=$(ls -t "$CORR"/*.campaign.log 2>/dev/null | head -1)
        [ -z "$newest" ] && { TAG=""; return; }
        TAG="$(basename "$newest" .campaign.log)"
        return
    fi
    TAG="$(basename "$newest" .csv)"
}

show() {
    resolve
    echo "───────────────────────────────────────────────  $(date '+%H:%M:%S')"
    if [ -z "$TAG" ]; then
        echo "no campaign log under $CORR"
        return
    fi
    echo "campaign: $TAG"

    # --- which phase is live -------------------------------------------------
    # Ordered generic to specific: the last match wins. The chain check comes
    # first so that the gap between two campaigns - building fifteen indexes and
    # updating statistics on 60 million rows, which is tens of minutes of real
    # work - does not report as "idle" merely because no Python process is up.
    local phase="idle"
    pgrep -f "chain_.*\.sh" >/dev/null 2>&1 && phase="BETWEEN CAMPAIGNS (index build / handover)"
    pgrep -f "validate_queries.py" >/dev/null 2>&1 && phase="VALIDATING"
    pgrep -f "run_query.py"        >/dev/null 2>&1 && phase="MEASURING"
    pgrep -f "load_pg.py|load_mysql.py|load_oracle.py|load_sqlserver.py|load_tpcc.py" >/dev/null 2>&1 && phase="LOADING"
    pgrep -f "oracle_groups.py" >/dev/null 2>&1 && phase="BUILDING WORKING SET (Oracle)"
    echo "phase: $phase"

    # --- progress through the 22 queries ------------------------------------
    local vlog="$CORR/$TAG.validate.log"
    if [ -f "$vlog" ]; then
        local nv nfail
        nv=$(grep -cE "^q[0-9]{2} " "$vlog" 2>/dev/null || echo 0)
        nfail=$(awk '$1 ~ /^q[0-9][0-9]$/ && !($2=="yes" && $3=="ok" && $4=="ok" && $5=="ok" && $6=="ok")' \
                    "$vlog" 2>/dev/null | wc -l | tr -d ' ')
        echo "validated: $nv/22   failing: $nfail"
        grep -E "^q[0-9]{2} " "$vlog" 2>/dev/null | tail -1 | sed 's/^/  last: /'
    fi

    # --- measured cells so far ----------------------------------------------
    # Three different units are easy to confuse here, so print all three.
    # The measurements file holds one row per (query, framework, access path):
    # 22 x 2 x 2 = 88 rows. all_results.csv holds one row per (framework, query)
    # with the SQL and ORM timings as *columns*: 22 x 2 = 44 cells. An earlier
    # version of this script divided neither, and reported the raw row count
    # against the 44-cell denominator - so 8 finished queries read as "32/44".
    local mfile="$CORR/measurements/$TAG.csv"
    if [ -f "$mfile" ]; then
        # Counted with a real CSV parser, not wc -l and not a line-oriented awk.
        # psycopg2 and oracledb put newlines inside their error text, so the
        # status_note of a failed path spans several physical lines and one
        # record is not one line. Both shortcuts overcounted: a file holding 68
        # records read as 75 "rows" with 12 "non-ok" against an actual 5, which
        # is a status display that invents failures.
        "${PYTHON:-$REPO/venv/bin/python}" - "$mfile" <<'PYEOF' 2>/dev/null
import csv, sys, collections
rows = list(csv.DictReader(open(sys.argv[1], newline="")))
last = {}
for r in rows:
    last[(r["query_id"], r["framework"], r["path"])] = r
n = len(last)
bad = [k for k, v in last.items() if v["status"] != "ok"]
print("measured: %d/22 queries   %d/44 cells   (%d/88 paths)"
      % (n // 4, n // 2, n))
if bad:
    print("  non-ok: %d  (%s)" % (len(bad),
          ", ".join("%s/%s/%s" % (q, f[:2], p) for q, f, p in sorted(bad)[:6])
          + (" ..." if len(bad) > 6 else "")))
PYEOF
    fi
    local clog="$CORR/$TAG.campaign.log"
    [ -f "$clog" ] && grep -E "^=== Q" "$clog" 2>/dev/null | tail -1 | sed 's/^/  now on: /'

    # --- what the server is actually executing -------------------------------
    for c in orm-bench-sqlserver orm-bench-mysql orm-bench-postgresql orm-bench-oracle; do
        docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$c" || continue
        case "$c" in
        orm-bench-mysql)
            docker exec "$c" mysql -uroot -pbench -N -e "
                SELECT CONCAT('  ', time, 's  ', LEFT(REPLACE(REPLACE(info,'\n',' '),'  ',''), 72))
                FROM information_schema.processlist
                WHERE command <> 'Sleep' AND info IS NOT NULL
                  AND info NOT LIKE '%processlist%';" 2>/dev/null \
                | sed "s/^/[$c] /"
            ;;
        orm-bench-postgresql)
            docker exec "$c" psql -U benchmark -d tpch -t -A -F'  ' -c "
                SELECT ROUND(EXTRACT(EPOCH FROM now()-query_start))||'s',
                       LEFT(REGEXP_REPLACE(query, '\s+', ' ', 'g'), 72)
                FROM pg_stat_activity
                WHERE state='active' AND pid<>pg_backend_pid();" 2>/dev/null \
                | sed "s/^/[$c] /"
            ;;
        orm-bench-sqlserver)
            # sqlcmd lives in mssql-tools18 on current images and mssql-tools on
            # older ones; -C trusts the container's self-signed certificate and
            # only exists on 18.
            local sqlcmd="/opt/mssql-tools18/bin/sqlcmd -C"
            docker exec "$c" test -x /opt/mssql-tools18/bin/sqlcmd 2>/dev/null \
                || sqlcmd="/opt/mssql-tools/bin/sqlcmd"
            docker exec "$c" $sqlcmd -S localhost -U sa \
                -P "${SQLSERVER_SA_PASSWORD:-YourStrong!Passw0rd}" -d tpch -h -1 -W -Q "
                SET NOCOUNT ON;
                SELECT '  ' + CAST(r.total_elapsed_time/1000 AS VARCHAR) + 's  '
                       + LEFT(REPLACE(REPLACE(t.text, CHAR(10),' '), CHAR(13),' '), 72)
                FROM sys.dm_exec_requests r
                CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t
                WHERE r.session_id <> @@SPID AND r.session_id > 50;" 2>/dev/null \
                | grep -v '^$' | sed "s/^/[$c] /"
            ;;
        orm-bench-oracle)
            docker exec "$c" bash -lc "echo \"
                SET HEADING OFF FEEDBACK OFF PAGESIZE 0;
                SELECT '  '||ROUND(elapsed_time/1000000)||'s  '||SUBSTR(sql_text,1,72)
                  FROM v\\\$session s JOIN v\\\$sql q ON s.sql_id=q.sql_id
                 WHERE s.status='ACTIVE' AND s.username IS NOT NULL;
                EXIT;\" | sqlplus -s / as sysdba" 2>/dev/null \
                | grep -v '^$' | sed "s/^/[$c] /"
            ;;
        esac
        docker stats --no-stream --format "[$c] cpu={{.CPUPerc}} mem={{.MemUsage}}" "$c" 2>/dev/null
    done
}

if [ "$WATCH" = "1" ]; then
    while true; do show; sleep 20; done
else
    show
fi
