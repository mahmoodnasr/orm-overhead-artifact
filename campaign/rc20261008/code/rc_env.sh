# Source, do not execute:   source code/rc_env.sh <engine> [tpch|tpcc] [scale]
# Campaign rc20261008 environment on the benchmark host. Credentials come from
# the repository's campaign-env.sh (the values the campaigns have always used)
# and from the settings modules' defaults; nothing here prints them.
RC_ENGINE="${1:?engine}"
RC_KIND="${2:-tpch}"
RC_SCALE="${3:-1}"
RC_CAMPAIGN=<campaign>
RC_SITE=<source-repo>/venv/lib/python3.12/site-packages
source "$RC_CAMPAIGN/src/scripts/0-host/campaign-env.sh" "$RC_ENGINE" "$RC_KIND" >/dev/null 2>&1
# Oracle keeps TPC-C in its own schema; run_system.sh uses TPCC_ORACLE_USER
# (default tpcc) with the same password variable.
if [ "$RC_ENGINE" = oracle ] && [ "$RC_KIND" = tpcc ]; then export ORACLE_USER="${TPCC_ORACLE_USER:-tpcc}"; unset SA_DSN; fi
# RC_SRCDIR selects the source worktree: src (phases A, D, E, F, B) or src-c
# (phase C, with the two TPC-C baseline corrections).
export PYTHONPATH="${RC_SRCDIR:-$RC_CAMPAIGN/src}:$RC_SITE"
export TPCH_SF="$RC_SCALE"
export PYTHONUNBUFFERED=1
export ORACLE_SID=free
# The Commercial System A settings module bounds every Django call with QUERY_TIMEOUT;
# the runner re-sets and reads back the ceiling on both frameworks anyway.
export QUERY_TIMEOUT=900
RC_PY=/usr/bin/python3.12
# Phase D: the SF2 data live beside SF1 in their own database (Oracle: their
# own schema). Only the TPC-H target moves; credentials are unchanged.
if [ "$RC_KIND" = tpch ] && [ "$RC_SCALE" != 1 ]; then
  RC_DB="tpch_sf${RC_SCALE}"
  case "$RC_ENGINE" in
    postgresql) export POSTGRES_DB="$RC_DB"; export SA_DSN="${SA_DSN%/tpch}/$RC_DB" ;;
    mysql)      export MYSQL_DB="$RC_DB";    export SA_DSN="${SA_DSN%/tpch}/$RC_DB" ;;
    sqlserver)  export SQLSERVER_DB="$RC_DB"; export SA_DSN="${SA_DSN/\/tpch\?/\/$RC_DB?}" ;;
    oracle)     export ORACLE_USER="${RC_ORACLE_SF2_USER:-TPCH_SF2}"; unset SA_DSN ;;
  esac
fi
# run_block.py (used by the historical preflight probe) builds its SQLAlchemy
# engine from SA_DSN, which campaign-env.sh leaves unset for Oracle.
if [ "$RC_ENGINE" = oracle ] && [ -z "${SA_DSN:-}" ]; then
  export SA_DSN="$(cd "$RC_CAMPAIGN/src" && DJANGO_SETTINGS_MODULE=settings_oracle $RC_PY -c '
import settings_oracle as s
d = s.DATABASES["default"]; loc, svc = d["NAME"].rsplit("/", 1)
from urllib.parse import quote
print("oracle+oracledb://%s:%s@%s/?service_name=%s" % (d["USER"], quote(d["PASSWORD"], safe=""), loc, svc))')"
fi
