# Source, do not execute:   source code/rc_g_env.sh <engine>
# Phase G (second server): the four engines run in containers on this Mac,
# one at a time, each limited to 2 CPUs and 3 GB like the benchmark host's
# cgroup envelope; the client runs on the Mac outside the VM. Same settings
# modules and credentials as the host (from the repository's campaign-env.sh
# and the settings defaults), only host and port differ. Nothing is printed.
RC_ENGINE="${1:?engine}"
RC_MODE="${2:-mac}"     # mac: client on macOS; container: client in the pinned rcg-client container
RC_CAMPAIGN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RC_SRC="${RC_SRC:-$HOME/rc20261008-client/src}"
if [ "$RC_MODE" = container ]; then RC_PY=python; else RC_PY="$HOME/rc20261008-client/venv/bin/python"; fi
source "$RC_SRC/scripts/0-host/campaign-env.sh" "$RC_ENGINE" tpch >/dev/null 2>&1
set +u
export PYTHONPATH="$RC_SRC"
export TPCH_SF=1 PYTHONUNBUFFERED=1 QUERY_TIMEOUT=900
# macOS only: Homebrew's default openssl is now 4.x and the vendor's ODBC Driver
# 18 for macOS loads OpenSSL 3 ("SSL Provider: OpenSSL library could not be
# loaded"). Setup, load and fingerprint steps run here; measurements run in the
# Linux client container and are unaffected.
[ "$RC_MODE" = container ] || export DYLD_LIBRARY_PATH=/opt/homebrew/opt/openssl@3/lib
if [ "$RC_MODE" = container ]; then
  # inside the VM network: the database container by name, on its own port
  case "$RC_ENGINE" in
    postgresql) export POSTGRES_HOST=rcg-postgresql POSTGRES_PORT=5432; export SA_DSN="${SA_DSN/127.0.0.1:5432/rcg-postgresql:5432}" ;;
    mysql)      export MYSQL_HOST=rcg-mysql MYSQL_PORT=3306; export SA_DSN="${SA_DSN/127.0.0.1:3306/rcg-mysql:3306}" ;;
    sqlserver)  export SQLSERVER_HOST=rcg-sqlserver SQLSERVER_PORT=1433; export SA_DSN="${SA_DSN/127.0.0.1:1433/rcg-sqlserver:1433}" ;;
    oracle)     export ORACLE_HOST=rcg-oracle ORACLE_PORT=1521 ORACLE_SERVICE=FREEPDB1
                export SA_DSN="$(cd "$RC_SRC" && DJANGO_SETTINGS_MODULE=settings_oracle "$RC_PY" -c '
import settings_oracle as s
d = s.DATABASES["default"]; loc, svc = d["NAME"].rsplit("/", 1)
from urllib.parse import quote
print("oracle+oracledb://%s:%s@%s/?service_name=%s" % (d["USER"], quote(d["PASSWORD"], safe=""), loc, svc))')" ;;
  esac
else
case "$RC_ENGINE" in
  postgresql) export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=15432; export SA_DSN="${SA_DSN/127.0.0.1:5432/127.0.0.1:15432}" ;;
  mysql)      export MYSQL_HOST=127.0.0.1 MYSQL_PORT=13306;       export SA_DSN="${SA_DSN/127.0.0.1:3306/127.0.0.1:13306}" ;;
  sqlserver)  export SQLSERVER_HOST=127.0.0.1 SQLSERVER_PORT=11433; export SA_DSN="${SA_DSN/127.0.0.1:1433/127.0.0.1:11433}" ;;
  oracle)     export ORACLE_HOST=127.0.0.1 ORACLE_PORT=11521 ORACLE_SERVICE=FREEPDB1
              export SA_DSN="$(cd "$RC_SRC" && DJANGO_SETTINGS_MODULE=settings_oracle "$RC_PY" -c '
import settings_oracle as s
d = s.DATABASES["default"]; loc, svc = d["NAME"].rsplit("/", 1)
from urllib.parse import quote
print("oracle+oracledb://%s:%s@%s/?service_name=%s" % (d["USER"], quote(d["PASSWORD"], safe=""), loc, svc))')" ;;
esac
fi
