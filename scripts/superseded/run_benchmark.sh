#!/usr/bin/env bash
# Unified Benchmark Runner
#
# Purpose:
#   Friendly wrapper around the Python runners to make it easy to:
#   - run a single database ("one by one")
#   - run multiple databases sequentially
#   - pick specific queries or run all
#   - control repetitions and output directory
#
# Usage examples:
#   ./scripts/run_benchmark.sh --db default --all --repetitions 3
#   ./scripts/run_benchmark.sh --db mysql --queries 1,6,8,9 --repetitions 3
#   ./scripts/run_benchmark.sh --db all --all --repetitions 3 --output results/raw
#   ./scripts/run_benchmark.sh --auto --all  # auto-detect available DBs
#
# DB aliases:
#   default = PostgreSQL
#   mysql   = MySQL
#   oracle  = Oracle
#   sqlserver = Microsoft SQL Server

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR%/scripts}"
cd "$PROJECT_DIR"

show_help() {
  cat <<EOF
Unified Benchmark Runner

Usage:
  $(basename "$0") [options]

Options:
  --db <alias>             Database to test: default|mysql|oracle|sqlserver|all (default: auto)
  --databases <list>       Comma-separated list of DB aliases (overrides --db)
  --auto                   Auto-detect available databases (connection test)
  --queries <list>         Comma-separated query numbers, e.g., 1,6,8,9
  --all                    Run all 22 TPC-H queries
  --schema-configs <list>  Schema configs (default: indexed)
  --repetitions <n>        Number of repetitions (first is warmup, default: 5)
  --output <dir>           Output directory (default: results/raw)
  --skip-connection-test   Skip database connection test in auto mode
  --no-venv                Do not try to activate ./venv
  -h, --help               Show this help

Examples:
  # Run all queries on PostgreSQL only
  $(basename "$0") --db default --all --repetitions 3

  # Run a subset on MySQL only
  $(basename "$0") --db mysql --queries 1,6,8,9 --repetitions 3

  # Run all databases sequentially
  $(basename "$0") --db all --all --repetitions 3 --output results/raw

  # Auto-detect available DBs and run all queries
  $(basename "$0") --auto --all --repetitions 3

Results CSV files will be placed under the specified --output directory.
EOF
}

# Defaults
DB_MODE="auto"
DATABASES_OVERRIDE=""
QUERIES=""
RUN_ALL="false"
SCHEMA_CONFIGS="indexed"
REPETITIONS=5
OUTPUT_DIR="results/raw"
SKIP_CONN_TEST="false"
USE_VENV="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db)
      DB_MODE="$2"; shift 2 ;;
    --databases)
      DATABASES_OVERRIDE="$2"; shift 2 ;;
    --auto)
      DB_MODE="auto"; shift ;;
    --queries)
      QUERIES="$2"; shift 2 ;;
    --all)
      RUN_ALL="true"; shift ;;
    --schema-configs)
      SCHEMA_CONFIGS="$2"; shift 2 ;;
    --repetitions)
      REPETITIONS="$2"; shift 2 ;;
    --output)
      OUTPUT_DIR="$2"; shift 2 ;;
    --skip-connection-test)
      SKIP_CONN_TEST="true"; shift ;;
    --no-venv)
      USE_VENV="false"; shift ;;
    -h|--help)
      show_help; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      show_help
      exit 2
      ;;
  esac
done

if [[ "$RUN_ALL" != "true" && -z "$QUERIES" ]]; then
  echo "Error: Specify either --all or --queries" >&2
  echo "" >&2
  show_help
  exit 2
fi

# Try to activate virtualenv
if [[ "$USE_VENV" == "true" && -f "venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

PY=python
command -v python3 >/dev/null 2>&1 && PY=python3

RUNNER="scripts/run_all_databases_benchmark.py"

CMD=("$PY" "$RUNNER" "--schema-configs" "$SCHEMA_CONFIGS" "--repetitions" "$REPETITIONS" "--output" "$OUTPUT_DIR")

if [[ -n "$DATABASES_OVERRIDE" ]]; then
  CMD+=("--databases" "$DATABASES_OVERRIDE")
else
  case "$DB_MODE" in
    default|mysql|oracle|sqlserver)
      CMD+=("--databases" "$DB_MODE")
      ;;
    all)
      CMD+=("--databases" "default,mysql,oracle,sqlserver")
      ;;
    auto)
      if [[ "$SKIP_CONN_TEST" == "true" ]]; then
        CMD+=("--skip-connection-test")
      fi
      # no explicit --databases -> script will auto-detect
      ;;
    *)
      echo "Invalid --db value: $DB_MODE" >&2
      show_help
      exit 2
      ;;
  esac
fi

if [[ "$RUN_ALL" == "true" ]]; then
  CMD+=("--all")
else
  CMD+=("--queries" "$QUERIES")
fi

echo "Running: ${CMD[*]}"
"${CMD[@]}"
