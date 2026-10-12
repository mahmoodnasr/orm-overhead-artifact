#!/bin/bash
# Start phase E by itself when the host's last visit (plan visits3) finishes,
# overnight (the author, 2026-10-10 21:40: "yes, set it up that way").
#
# 1. Keep the Mac awake while waiting (it must stay on AC power, lid open).
# 2. Poll the host every 60 s until visits3b (Oracle non-indexed TPC-C
#    re-measured alone, started by rc-switch-visits3b when visits3 ends) reports
#    controller_done. A new failed step in visits3 (anything after the 03:23
#    PostgreSQL SF2 load failure, already fixed) or any in visits3b stops the
#    wait: E does not start over a host that needs attention.
# 2b. Vault snapshot after-host-visits, with the host idle (the after-phase-F
#    snapshot overlapped Oracle's TPC-C run - never again during measurement).
#    A failed snapshot stops here.
# 3. Quit Google Drive gracefully (it would compete for the Wi-Fi link; the
#    driver refuses to start while it runs) and confirm it has stopped. If it
#    does not stop within two minutes, E does not start.
# 4. Run the E driver (Oracle first, the engine the host is left on).
# 5. Reopen Google Drive only if E completed; if E halted, Drive stays closed
#    until E is resumed.
# Log: E-client/autostart.log.
set -uo pipefail
CAMP="$(cd "$(dirname "$0")/.." && pwd)"; cd "$CAMP"
mkdir -p E-client
LOG=E-client/autostart.log
say() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }
EV=<campaign>/controller/visits3-events.jsonl
EVB=<campaign>/controller/visits3b-events.jsonl
hs() { ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=4 user@<host-ip> "$@"; }

caffeinate -dimsu -w $$ &
say "waiting for visits3, then visits3b, to finish"
while true; do
  # judged by the events after each plan's latest controller_start (code/rc_plan_state.py)
  st=$(hs "a=\$(python3 $(dirname $EV)/../code/rc_plan_state.py $EV); b=\$(python3 $(dirname $EV)/../code/rc_plan_state.py $EVB); if [ \$a = failed ] || [ \$b = failed ]; then echo failed; elif [ \$b = done ]; then echo done; else echo running; fi" 2>/dev/null) || st=unreachable
  case "$st" in
    done) say "visits3 and visits3b finished"; break ;;
    failed) say "visits3 or visits3b has a new failed step; E not started"; exit 2 ;;
  esac
  sleep 60
done
if [ -f E-client/steps/vault-after-host-visits.done ]; then
  say "vault snapshot after-host-visits already taken; skipped"
else
  say "vault snapshot after-host-visits (host idle)"
  if ! /bin/bash code/rc_vault.sh after-host-visits >> "$LOG" 2>&1; then say "vault snapshot failed; E not started"; exit 4; fi
  mkdir -p E-client/steps; date -u +%FT%TZ > E-client/steps/vault-after-host-visits.done
fi
if pgrep -x "Google Drive" >/dev/null; then
  # graceful quit only (approved). Drive declines a quit while it is uploading
  # ("User canceled", -128, 2026-10-11 02:37), so ask again every 5 min, up to
  # an hour; never force it.
  for try in $(seq 1 12); do
    # never send the quit to an app that is not running: AppleScript may launch it
    pgrep -x "Google Drive" >/dev/null || break
    say "quitting Google Drive (attempt $try)"
    osascript -e 'quit app "Google Drive"' >> "$LOG" 2>&1
    for _ in $(seq 1 24); do pgrep -x "Google Drive" >/dev/null || break; sleep 5; done
    pgrep -x "Google Drive" >/dev/null || break
    sleep 180
  done
  if pgrep -x "Google Drive" >/dev/null; then
    # no more quit requests; wait (up to 12 h) for the author to quit it, then start
    say "Google Drive declined to quit for an hour; waiting for it to be quit by hand"
    for _ in $(seq 1 720); do pgrep -x "Google Drive" >/dev/null || break; sleep 60; done
    if pgrep -x "Google Drive" >/dev/null; then say "Google Drive still running after 12 h; E not started"; exit 3; fi
  fi
  say "Google Drive stopped"
  DRIVE_WAS_RUNNING=1
else
  DRIVE_WAS_RUNNING=0
fi
say "starting the E driver"
/bin/bash code/rc_e_driver.sh oracle sqlserver postgresql mysql >> E-client/driver.log 2>&1
rc=$?
if [ $rc -eq 0 ] && grep -q "E driver complete" E-client/driver.log; then
  say "E complete"
  [ "$DRIVE_WAS_RUNNING" = 1 ] && { open -a "Google Drive"; say "Google Drive reopened"; }
else
  say "E driver stopped (exit $rc; see E-client/driver.log and E-client/HALTED); Google Drive left closed until E is resumed"
fi
