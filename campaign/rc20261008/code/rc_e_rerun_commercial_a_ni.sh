#!/bin/bash
# Re-measure phase E's Commercial System A non-indexed cells on a freshly started engine
# (the author, 2026-10-11: "Re-measure + reproduce cause").
#
# E measured Commercial System A non-indexed right after its 2.5 h indexed run on the
# same instance (indexes dropped, no restart), and its full scans ran
# 2.3-3.8x slower than phase A, which measured non-indexed on a freshly started
# engine. The client was ruled out (identical driver 18.7, SET options and
# plans; evidence/client-plans/). This run repeats the E cells in A's order:
# engine restarted, non-indexed verified, then the Mac client - same protocol
# (E-v1), runner, client container, records, network logging and watchdog as
# the E driver, whose functions are read from code/rc_e_driver.sh unchanged.
# New run directory E-client/commercial_a-non-indexed-r2; the first run is kept,
# superseded. Steps in E-client/steps-r2. Usage (Mac):
#   nohup /bin/bash code/rc_e_rerun_commercial_a_ni.sh > E-client/rerun-commercial_a-ni.log 2>&1 &
set -uo pipefail
CAMP="$(cd "$(dirname "$0")/.." && pwd)"; cd "$CAMP"
SRC="$HOME/rc20261008-client/src"
HOSTSSH=user@<host-ip>
DBH=<host-ip>
H=<campaign>
OUT=E-client
PROTO=protocols/rc20261008-E-v1.json
STEPS=$OUT/steps-r2; mkdir -p $STEPS $OUT/host $OUT/network $OUT/client $OUT/logs
# the E driver's own functions, verbatim
eval "$(sed -n '/^port() {/,/^export CAMP/p' code/rc_e_driver.sh | sed '$d')"
ts() { date -u +%Y%m%dT%H%M%SZ; }
hs() { ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=4 $HOSTSSH "$@"; }
step() {
  local id=$1; shift
  [ -f "$STEPS/$id.done" ] && { echo "skip $id"; return 0; }
  echo "### $(date -u +%FT%TZ) $id"
  if /bin/bash -c "$*"; then date -u +%FT%TZ > "$STEPS/$id.done"; else echo "$id" > "$OUT/HALTED-r2"; echo "HALTED at $id"; exit 1; fi
}
export -f client reach host_plan host_record net_record client_record run_cell_set hs ts port
export CAMP SRC HOSTSSH DBH H OUT PROTO
pgrep -x "Google Drive" >/dev/null && { echo "Google Drive is running; quit it first"; exit 2; }
caffeinate -dimsu -w $$ &
step "host-fresh" "host_plan E2-sqlserver-a"
step "root-firewall" "hs 'sudo -n /usr/local/sbin/rc-campaign-root firewall'"
step "reach" "reach sqlserver"
step "run-non-indexed" "run_cell_set sqlserver non-indexed $OUT/sqlserver-non-indexed-r2 '6 17 18 20 21'"
step "verify-non-indexed" "python3 code/rc_verify.py $OUT/sqlserver-non-indexed-r2 --campaign-dir . --write"
step "root-firewall-undo" "hs 'sudo -n /usr/local/sbin/rc-campaign-root undo-firewall'"
step "host-fp-after" "host_plan E2-sqlserver-c"
echo "rerun complete $(date -u +%FT%TZ)"
