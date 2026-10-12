# Source, do not execute, inside the pinned client container:
#   source code/rc_e_env.sh <engine>
# Phase E (separate client): the client container on this Mac, the databases
# on the benchmark host over the LAN. Everything is the host's rc_env.sh for
# TPC-H at SF1 - the same campaign-env.sh credentials, settings modules,
# TPCH_SF=1, QUERY_TIMEOUT=900 - except the address: 127.0.0.1 becomes the
# host's LAN address, on each engine's own port. Nothing is printed.
RC_ENGINE="${1:?engine}"
RC_DB_HOST=<host-ip>
RC_CAMPAIGN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RC_SRC="${RC_SRC:-$HOME/rc20261008-client/src}"
RC_PY=python
source "$RC_SRC/scripts/0-host/campaign-env.sh" "$RC_ENGINE" tpch >/dev/null 2>&1
set +u
export PYTHONPATH="$RC_SRC"
export TPCH_SF=1 PYTHONUNBUFFERED=1 QUERY_TIMEOUT=900
case "$RC_ENGINE" in
  postgresql) export POSTGRES_HOST=$RC_DB_HOST POSTGRES_PORT=5432; export SA_DSN="${SA_DSN/127.0.0.1:5432/$RC_DB_HOST:5432}" ;;
  mysql)      export MYSQL_HOST=$RC_DB_HOST MYSQL_PORT=3306;       export SA_DSN="${SA_DSN/127.0.0.1:3306/$RC_DB_HOST:3306}" ;;
  sqlserver)  export SQLSERVER_HOST=$RC_DB_HOST SQLSERVER_PORT=1433; export SA_DSN="${SA_DSN/127.0.0.1:1433/$RC_DB_HOST:1433}" ;;
  oracle)     export ORACLE_HOST=$RC_DB_HOST ORACLE_PORT=1521 ORACLE_SERVICE=FREEPDB1
              export SA_DSN="$(cd "$RC_SRC" && DJANGO_SETTINGS_MODULE=settings_oracle "$RC_PY" -c '
import settings_oracle as s
d = s.DATABASES["default"]; loc, svc = d["NAME"].rsplit("/", 1)
from urllib.parse import quote
print("oracle+oracledb://%s:%s@%s/?service_name=%s" % (d["USER"], quote(d["PASSWORD"], safe=""), loc, svc))')" ;;
esac
# refuse to run against anything but the host's LAN address
case "$SA_DSN" in *"@$RC_DB_HOST:"*|*"@$RC_DB_HOST/"*) ;; *) echo "rc_e_env: SA_DSN does not point at $RC_DB_HOST" >&2; return 1 ;; esac
