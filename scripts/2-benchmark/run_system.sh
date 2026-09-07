#!/usr/bin/env bash
# One system, end to end, in the order that costs the fewest index transitions.
#
#     scripts/2-benchmark/run_system.sh postgresql
#     scripts/2-benchmark/run_system.sh oracle
#
# What it does, per configuration:
#
#     preflight  ->  TPC-H campaign  ->  gate  ->  TPC-C latency  ->  throughput
#
# and between the two configurations, exactly one `manage_indexes --action drop`.
#
# Why indexed first
# -----------------
# A freshly loaded schema is the non-indexed configuration and measuring it
# first costs no setup, which is why SHAKEDOWN_PLAN.md specifies that order. It
# stopped being the cheap order on 2026-09-05: validating the heavy queries
# required the indexes, because Q17, Q20 and Q21 exceed any sane validation
# ceiling without them and a timeout validates neither correctness nor its
# absence. All four engines are therefore indexed with fresh statistics, and
# indexed-first now costs one drop where non-indexed-first would cost a drop
# and a create. The rule is not "non-indexed first", it is "start from the
# state the database is already in".
#
# Nothing here is optional. Every campaign is preceded by preflight.py, which
# refuses on a host that is not campaign-ready, on an engine that is still
# adapting (Query Store, unbuilt statistics, Oracle's result cache), on an
# index state that disagrees with the label the rows will carry, and on a
# protocol probe that finds position or block-half bias. Every campaign is
# followed by pilot_gate.py, and a non-zero gate stops the sequence rather than
# letting the next configuration start on top of a bad one.
set -uo pipefail

E="${1:?usage: run_system.sh <postgresql|mysql|sqlserver|oracle>}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

ALIAS="$E"; [ "$E" = postgresql ] && ALIAS=default
SF="${TPCH_SF:?TPCH_SF must be set}"
SFDIR="results/sf${SF}/measurements"

step() { echo; echo "############ $* ############"; }
die()  { echo; echo "STOPPED: $*" >&2; exit 1; }

step "$E: host envelope"
sudo bench-host apply "$E"  || die "could not apply the envelope"
sudo bench-host verify "$E" || die "host is not campaign-ready"

# Let the machine settle before probing it. `apply` stops the other three
# engines, and a stopping engine is not an idle one: SQL Server flushes a
# 1.5 GB buffer pool and checkpoints on the way down. Oracle's first preflight
# ran into exactly that and refused - a +11.4% position effect and 22.3% drift
# between block halves, both of which fell to +3.6% and +1.5% once the disk had
# gone quiet. The probe was right to refuse; the chain was wrong to ask so soon.
step "$E: settling for ${BENCH_SETTLE:-90}s after the engine switch"
sleep "${BENCH_SETTLE:-90}"

for SCHEMA in indexed non-indexed; do
    if [ "$SCHEMA" = non-indexed ]; then
        step "$E: dropping indexes - the one transition this ordering needs"
        python3 scripts/1-setup/manage_indexes.py --database "$ALIAS" --action drop \
            || die "index drop failed"
        python3 scripts/1-setup/manage_indexes.py --database "$ALIAS" --benchmark tpcc \
            --action drop || die "TPC-C index drop failed"
    fi

    step "$E $SCHEMA: preflight"
    python3 scripts/0-host/preflight.py --dbms "$E" --schema "$SCHEMA" \
        || die "preflight refused $E $SCHEMA"

    step "$E $SCHEMA: TPC-H, 22 queries x 8 blocks x 4 paths"
    bash scripts/2-benchmark/run_pilot.sh "$E" "$SCHEMA" campaign \
        || die "TPC-H campaign failed"

    # GATE_ADVISORY=1 records a gate failure and continues instead of stopping
    # the chain. It exists for one situation and should be used for no other:
    # a failure whose cause has been diagnosed, which does not put the
    # measurements in doubt, and which is a question about how to report rather
    # than whether to keep. SQL Server indexed is the case - section 8.1's CV is
    # computed across blocks, each with its own parameter set, so for a query
    # whose runtime depends on its parameters it measures parameter sensitivity
    # and not noise. Removing the per-block effect takes that run's p90 from
    # 23.50% to 14.70%, and the pattern reproduces block for block on an
    # independent re-run. The plan already concedes the point for Q18 in section
    # 2.1. Every advisory failure is printed here and must be disclosed.
    step "$E $SCHEMA: gate"
    GATE_CEILING=""
    [ "$E" = sqlserver ] && GATE_CEILING="--ceiling ${PILOT_TIMEOUT:-900}"
    if ! python3 scripts/4-analysis/pilot_gate.py \
            "$SFDIR/${E}_${SCHEMA//-/_}.csv" $GATE_CEILING; then
        if [ "${GATE_ADVISORY:-0}" = "1" ]; then
            echo "GATE FAILED for $E $SCHEMA - continuing under GATE_ADVISORY=1."
            echo "This run must be disclosed as failing its pre-registered bound."
            echo "$E $SCHEMA" >> "$SFDIR/.gate_failures"
        else
            die "gate failed for $E $SCHEMA"
        fi
    fi

    step "$E $SCHEMA: TPC-C latency"
    bash scripts/2-benchmark/run_tpcc_campaign.sh "$E" "$SCHEMA" \
        || die "TPC-C latency failed"

    # The throughput harness is invoked directly rather than through
    # run_tpcc_campaign.sh, so it needs the same TPC-C environment that script
    # builds - otherwise it inherits the TPC-H database and every transaction
    # fails on a missing warehouse table.
    step "$E $SCHEMA: TPC-C throughput curve"
    case "$E" in
      postgresql) export POSTGRES_DB="${TPCC_POSTGRES_DB:-tpcc}"
                  export SA_DSN="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}" ;;
      mysql)      export MYSQL_DB="${TPCC_MYSQL_DB:-tpcc}"
                  export SA_DSN="mysql+mysqldb://${MYSQL_USER}:${MYSQL_PASSWORD}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DB}" ;;
      sqlserver)  export SQLSERVER_DB="${TPCC_SQLSERVER_DB:-tpcc}"
                  export SA_DSN="mssql+pyodbc://sa:YourStrong%21Passw0rd@${SQLSERVER_HOST}:${SQLSERVER_PORT}/${SQLSERVER_DB}?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes" ;;
      oracle)     export ORACLE_USER="${TPCC_ORACLE_USER:-tpcc}"
                  export SA_DSN="oracle+oracledb://${ORACLE_USER}:${ORACLE_PASSWORD}@${ORACLE_HOST}:${ORACLE_PORT}/?service_name=${ORACLE_SERVICE}" ;;
    esac
    for c in 1 4 8 16 32 50; do
        python3 scripts/2-benchmark/run_tpcc_throughput.py \
            --dbms "$E" --schema "$SCHEMA" --concurrency "$c" \
            --duration 60 --warmup 10 \
            --out "$SFDIR/${E}_tpcc_throughput_${SCHEMA//-/_}.csv" \
            || die "throughput failed at concurrency $c"
    done
    # Put the TPC-H target back before the next configuration's campaign.
    case "$E" in
      postgresql) export POSTGRES_DB=tpch
                  export SA_DSN="postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/tpch" ;;
      mysql)      export MYSQL_DB=tpch
                  export SA_DSN="mysql+mysqldb://${MYSQL_USER}:${MYSQL_PASSWORD}@${MYSQL_HOST}:${MYSQL_PORT}/tpch" ;;
      sqlserver)  export SQLSERVER_DB=tpch
                  export SA_DSN="mssql+pyodbc://sa:YourStrong%21Passw0rd@${SQLSERVER_HOST}:${SQLSERVER_PORT}/tpch?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes" ;;
      oracle)     export ORACLE_USER=tpch
                  export SA_DSN="oracle+oracledb://tpch:${ORACLE_PASSWORD}@${ORACLE_HOST}:${ORACLE_PORT}/?service_name=${ORACLE_SERVICE}" ;;
    esac
done

step "$E complete: both configurations, TPC-H and TPC-C, all gated"
