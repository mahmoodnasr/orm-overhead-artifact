#!/bin/bash
# Phase E driver (Mac): the Mac as a physically separate client of the
# benchmark host, over Wi-Fi at both ends (no wired adapter; the host's own
# Ethernet port is down). Protocol rc20261008-E-v1 (runner code/rc_e.py).
#
# Per engine: host plan E-<e>-a (engine on, SF1 fingerprint, LAN listener,
# first index state, preflight) -> root helper action the engine needs ->
# reachability from the client container -> cancellation pilot over the
# network -> [first engine only: the separate-client trial, which must pass
# before the long run] -> client run in the first state -> host plan E-<e>-b
# (other index state) -> client run -> host plan E-<e>-c (fingerprint) -> undo
# of the engine's root action.
#
# Every client run is bracketed by a host verification over ssh (bench-host
# verify, Oracle process affinity) and a network record (ping summary, Wi-Fi
# link at both ends, no network names or hardware addresses), with a ping log
# during the run. A watchdog kills a client whose progress file has not moved
# for 25 min (a dead socket can block past the 900 s statement limit); the
# run then resumes, up to three attempts.
#
# Markers in E-client/steps; HALTED names the failing step.
# Usage: nohup /bin/bash code/rc_e_driver.sh oracle commercial_a postgresql mysql > E-client/driver.log 2>&1 &
set -uo pipefail
CAMP="$(cd "$(dirname "$0")/.." && pwd)"; cd "$CAMP"
SRC="$HOME/rc20261008-client/src"
HOSTSSH=user@<host-ip>
DBH=<host-ip>
H=<campaign>
OUT=E-client; mkdir -p $OUT/steps $OUT/host $OUT/network $OUT/client $OUT/logs
PROTO=protocols/rc20261008-E-v1.json
Q="6 17 18 20 21"
TRIAL_DONE=$OUT/steps/trial.done
first_state()  { case "$1" in sqlserver) echo indexed ;; *) echo non-indexed ;; esac; }
other_state()  { [ "$1" = indexed ] && echo non-indexed || echo indexed; }
queries() {  # the five SF1 host-censored query cells are not run (as in G and D)
  if [ "$2" = non-indexed ]; then case "$1" in postgresql) echo "6 18"; return ;; mysql) echo "6 18 21"; return ;; esac; fi
  echo "$Q"; }
port() { case "$1" in postgresql) echo 5432 ;; mysql) echo 3306 ;; sqlserver) echo 1433 ;; oracle) echo 1521 ;; esac; }
ts() { date -u +%Y%m%dT%H%M%SZ; }
hs() { ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=4 $HOSTSSH "$@"; }

step() {
  local id=$1; shift
  [ -f "$OUT/steps/$id.done" ] && { echo "skip $id"; return 0; }
  echo "### $(date -u +%FT%TZ) $id"
  if /bin/bash -c "$*"; then date -u +%FT%TZ > "$OUT/steps/$id.done"; else echo "$id" > "$OUT/HALTED"; echo "HALTED at $id"; exit 1; fi
}

host_plan() {  # run plans/<id>.json with the host's controller under systemd; poll, surviving ssh drops
  local id=$1 n=0
  until hs "test -f $H/plans/$id.json"; do n=$((n+1)); [ $n -gt 20 ] && { echo "host unreachable or plan $id missing"; return 1; }; sleep 30; done
  if ! hs "grep -q controller_done $H/controller/$id-events.jsonl 2>/dev/null"; then
    hs "systemctl --user is-active -q rc-$id || systemd-run --user --unit rc-$id --working-directory=$H \
        --property=StandardOutput=append:$H/logs/controller-$id.out --property=StandardError=append:$H/logs/controller-$id.out \
        /usr/bin/python3.12 code/rc_controller.py plans/$id.json" || return 1
  fi
  while true; do
    st=$(hs "f=$H/controller/$id-events.jsonl; if grep -q step_failed \$f 2>/dev/null; then echo failed; elif grep -q controller_done \$f 2>/dev/null; then echo done; elif systemctl --user is-active -q rc-$id; then echo running; else echo stopped; fi" 2>/dev/null) || st=unreachable
    case "$st" in
      done) echo "host plan $id done"; return 0 ;;
      failed) echo "host plan $id FAILED:"; hs "grep step_failed $H/controller/$id-events.jsonl | cut -c1-800"; return 1 ;;
      stopped) echo "host plan $id stopped without finishing; relaunching (the controller resumes)"
               hs "systemd-run --user --unit rc-$id-r$(date +%s) --working-directory=$H /usr/bin/python3.12 code/rc_controller.py plans/$id.json" ;;
    esac
    sleep 30
  done
}

host_record() {  # host_record <engine> <file>: bench-host verify and Oracle affinity, over ssh
  # (code/rc_e_host_record.py runs on the host from stdin; no heredoc here: bash
  # cannot export a function holding one - found by the dry run, 2026-10-09)
  local e=$1 f=$2
  hs "python3 - $e" < "$CAMP/code/rc_e_host_record.py" > "$f.tmp" || return 1
  mv "$f.tmp" "$f"
  python3 -c "import json,sys; j=json.load(open('$f')); sys.exit(0 if not j['active_rc_units'].strip() else 'host is running another campaign unit: '+j['active_rc_units'])"
}

net_record() {  # net_record <file>: ping summary and the Mac's Wi-Fi link (no network name, no addresses)
  local f=$1
  { echo "{\"taken\": \"$(date -u +%FT%TZ)\","
    echo "\"ping\": $(ping -c 60 -i 0.5 $DBH 2>&1 | tail -2 | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),"
    echo "\"mac_wifi\": $(system_profiler SPAirPortDataType -json 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
keep = ("spairport_network_phymode", "spairport_network_channel", "spairport_network_rate", "spairport_signal_noise", "spairport_network_mcs")
cur = []
for ifc in d.get("SPAirPortDataType", [{}])[0].get("spairport_airport_interfaces", []):
    c = ifc.get("spairport_current_network_information")
    if c: cur.append({k: c.get(k) for k in keep})
print(json.dumps(cur))'),"
    echo "\"mac_power\": $(pmset -g batt | head -1 | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))')}"
  } > "$f"
  python3 -c "import json; json.load(open('$f'))"
}

client_record() {  # the Mac's hardware and software for the run inventory (no serial, no UUID)
  python3 "$CAMP/code/rc_e_client_record.py" "$1"
}

client() {  # client <engine> <runner args...>: the pinned client container, against the host
  local e=$1; shift
  docker run --rm --name rcg-e-client --cpuset-cpus 2,3 --cpus 2 --memory 3g --memory-swap 3g \
    -e RC_SRC="$SRC" -e RC_E_HOST_VERIFY="${RC_E_HOST_VERIFY:-}" -e RC_E_CLIENT_JSON="${RC_E_CLIENT_JSON:-}" \
    -v "$CAMP:$CAMP" -v "$SRC:$SRC" -w "$CAMP" rcg-client:3.12.3 \
    bash -c "source code/rc_e_env.sh $e && python code/rc_e.py --campaign-dir $CAMP --src $SRC --protocol $PROTO --dbms $e --client-cpus 2,3 $*"
}

reach() {  # TCP reachability of the engine from inside the client container
  local e=$1 p; p=$(port $e)
  docker run --rm rcg-client:3.12.3 python -c "import socket; socket.create_connection(('$DBH', $p), 10).close(); print('reachable $DBH:$p')"
}

run_cell_set() {  # run_cell_set <engine> <state> <run-dir> <queries> [extra runner args]
  local e=$1 s=$2 rd=$3 qs=$4; shift 4
  local tag; tag=$(basename "$rd")
  local attempt
  for attempt in 1 2 3; do
    local t; t=$(ts)
    # absolute: the runner changes to its source directory (rc_analytical.py:138)
    # before it reads them - with relative paths its gate found neither (06:54)
    export RC_E_HOST_VERIFY="$CAMP/$OUT/host/$tag-before-$t.json" RC_E_CLIENT_JSON="$CAMP/$OUT/client/$tag-$t.json"
    host_record "$e" "$RC_E_HOST_VERIFY" || return 1
    client_record "$RC_E_CLIENT_JSON"
    net_record "$OUT/network/$tag-before-$t.json" || return 1
    ( ping -i 1 $DBH | while IFS= read -r l; do echo "$(date -u +%FT%TZ) $l"; done ) >> "$OUT/network/$tag.ping.log" 2>&1 &
    local pinger=$!
    local resume=""; [ -d "$rd" ] && [ -n "$(ls -A "$rd" 2>/dev/null)" ] && resume="--resume"
    local clog="$OUT/logs/$tag-$t.log"
    client "$e" --run-dir "$rd" --schema "$s" --queries $qs "$@" $resume > "$clog" 2>&1 &
    local cpid=$!
    # watchdog: a client blocked on a dead socket does not move its progress file
    while kill -0 $cpid 2>/dev/null; do
      sleep 60
      local pf="$rd/progress.json"
      if [ -f "$pf" ] && [ $(( $(date +%s) - $(stat -f %m "$pf") )) -gt 1500 ]; then
        echo "watchdog: $pf unchanged for 25 min; killing the client (attempt $attempt)"
        docker kill rcg-e-client >/dev/null 2>&1
      fi
    done
    wait $cpid; local rc=$?
    pkill -P $pinger >/dev/null 2>&1; kill $pinger >/dev/null 2>&1
    host_record "$e" "$OUT/host/$tag-after-$t.json" || true
    net_record "$OUT/network/$tag-after-$t.json" || true
    tail -3 "$clog"
    [ $rc -eq 0 ] && return 0
    # not a network problem: a refused gate, failed end checks or a fatal record stop here
    if grep -qi "gate refused\|end checks failed\|fatal" "$clog"; then echo "client stopped for a non-network reason (see $clog)"; return 1; fi
    echo "client exit $rc (attempt $attempt); waiting for the network, then resuming"
    until ping -c 3 -t 5 $DBH >/dev/null 2>&1; do sleep 30; done
    sleep 30
  done
  return 1
}
export -f client reach host_plan host_record net_record client_record run_cell_set hs ts port
export CAMP SRC HOSTSSH DBH H OUT PROTO

step "mac-preconditions" "
  test \"\$(ipconfig getifaddr en0)\" = <client-ip> || { echo 'Mac IP is not <client-ip> (the root helper allows only that client)'; exit 1; }
  pmset -g batt | head -1 | grep -q 'AC Power' || { echo 'Mac not on AC power'; exit 1; }
  ! pgrep -f rc_v_driver.sh >/dev/null || { echo 'the redundant V run is still going; stop it first'; exit 1; }
  ! pgrep -x 'Google Drive' >/dev/null || { echo 'Google Drive is running; pause/quit it during E'; exit 1; }
  ! pgrep -if '/desktop-app' >/dev/null || { echo 'desktop-app is running'; exit 1; }
  others=\$(docker ps --format '{{.Names}}' | grep -v '^rcg-e-client\$' || true); [ -z \"\$others\" ] || { echo \"containers running: \$others\"; exit 1; }
  hs 'systemctl --user list-units \"rc-*\" --no-legend --plain --state=active | grep -v \"^rc-E-\"' && { echo 'host still running a campaign unit'; exit 1; } || true
  echo preconditions ok"
caffeinate -dimsu -w $$ &
step "root-firewall" "hs 'sudo -n /usr/local/sbin/rc-campaign-root firewall'"
for E in "$@"; do
  S1=$(first_state $E); S2=$(other_state $S1)
  [ $E = postgresql ] && step "$E-root-before" "hs 'sudo -n /usr/local/sbin/rc-campaign-root pg-client'"
  step "$E-host-a" "host_plan E-$E-a"
  case $E in
    mysql)  step "$E-root" "hs 'sudo -n /usr/local/sbin/rc-campaign-root mysql-client'" ;;
    oracle) step "$E-root" "hs 'sudo -n /usr/local/sbin/rc-campaign-root oracle-session-view'" ;;
  esac
  step "$E-reach" "reach $E"
  step "$E-cancel-pilot" "PD=$OUT/pilot-$E-cancel-\$(ts); run_cell_set $E $S1 \$PD '1' --mode pilot --cancel-test-query 1 --cancel-check-query 6 --cancel-limit 1 && python3 -c \"import json;d=json.load(open('\$PD/cancel-test/summary.json'));print(d['passed']);assert d['passed']\""
  if [ ! -f "$TRIAL_DONE" ]; then
    step "trial" "TD=$OUT/trial-$E-$S1; run_cell_set $E $S1 \$TD '6 18' --mode pilot --blocks 2 && python3 code/rc_verify.py \$TD --campaign-dir . --write"
  fi
  step "$E-run-$S1" "run_cell_set $E $S1 $OUT/$E-$S1 '$(queries $E $S1)'"
  step "$E-verify-$S1" "python3 code/rc_verify.py $OUT/$E-$S1 --campaign-dir . --write"
  step "$E-host-b" "host_plan E-$E-b"
  step "$E-run-$S2" "run_cell_set $E $S2 $OUT/$E-$S2 '$(queries $E $S2)'"
  step "$E-verify-$S2" "python3 code/rc_verify.py $OUT/$E-$S2 --campaign-dir . --write"
  step "$E-host-c" "host_plan E-$E-c"
  case $E in
    mysql)      step "$E-root-undo" "hs 'sudo -n /usr/local/sbin/rc-campaign-root undo-mysql-client'" ;;
    oracle)     step "$E-root-undo" "hs 'sudo -n /usr/local/sbin/rc-campaign-root undo-oracle-session-view'" ;;
    postgresql) step "$E-root-undo" "hs 'sudo -n /usr/local/sbin/rc-campaign-root undo-pg-client'" ;;
  esac
done
step "root-firewall-undo" "hs 'sudo -n /usr/local/sbin/rc-campaign-root undo-firewall'"
echo "E driver complete $(date -u +%FT%TZ)"
