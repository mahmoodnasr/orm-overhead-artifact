#!/usr/bin/env bash
# Start plan visits3b (Oracle non-indexed TPC-C re-measured alone) as soon as
# visits3 finishes; runs on the host under systemd-run --user. Does nothing if
# visits3 records a new failed step (anything after the 03:23 one).
set -u
D=<campaign>
E=$D/controller/visits3-events.jsonl
LOG=$D/logs/rc-switch-visits3b.log
say() { echo "$(date -Is) $*" >> "$LOG"; }
say "waiting for visits3 controller_done"
# state from the events after the latest controller_start (a resumed plan keeps
# earlier failures in the file): code/rc_plan_state.py
until [ "$(python3 $D/code/rc_plan_state.py "$E")" = done ]; do
  [ "$(python3 $D/code/rc_plan_state.py "$E")" = failed ] && { say "visits3 failed again; not starting visits3b"; exit 4; }
  sleep 5
done
for _ in $(seq 1 60); do systemctl --user is-active -q rc-visits3 || break; sleep 2; done
cd "$D" || exit 6
test ! -e controller/visits3b-state.json || { say "visits3b already has state"; exit 8; }
systemd-run --user --unit rc-visits3b --working-directory="$D" \
  --property=StandardOutput=append:"$D/logs/controller-visits3b.out" \
  --property=StandardError=append:"$D/logs/controller-visits3b.out" \
  /usr/bin/python3.12 code/rc_controller.py plans/visits3b.json >> "$LOG" 2>&1
say "rc-visits3b launched (exit $?)"
