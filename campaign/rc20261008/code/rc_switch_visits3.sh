#!/usr/bin/env bash
# Switch from plan visits2 to plan visits3 at the end of the Commercial System A part,
# unattended (2026-10-09). Runs on the host under systemd-run --user.
#
# visits3 (plans/visits3.json, rc_make_plan_visits3.py) is visits2 from its
# closing Commercial System A fingerprint on, with every F step under F-v3. The switch
# waits for visits2's last Commercial System A F step to finish, stops rc-visits2 at
# once - the controller is then starting that fingerprint, a read-only step
# that writes its record only after hashing every table, a minute or more
# later - and starts rc-visits3, which runs the fingerprint again. If that
# record were somehow already written, rc_fingerprint.py refuses to replace it
# and visits3 halts on its first step: a visible stop, nothing lost.
#
# Refuses to launch unless F-v3 is frozen, visits3 has never run, and no
# controller or runner process is left.
set -u
D=<campaign>
E=$D/controller/visits2-events.jsonl
LOG=$D/logs/rc-switch-visits3.log
say() { echo "$(date -Is) $*" >> "$LOG"; }

test -f "$E" || { say "no $E"; exit 3; }
say "waiting for step_done of sqlserver-F-indexed-django"
until grep -q '"event":"step_done".*"step":"sqlserver-F-indexed-django"' "$E"; do
  if grep -q '"event":"step_failed"\|"event":"controller_done"' "$E"; then
    say "visits2 failed or finished before the switch point; not switching"; exit 4
  fi
  sleep 0.5
done
systemctl --user stop rc-visits2.service
say "rc-visits2 stopped: $(tail -1 "$E" | cut -c1-200)"
for _ in $(seq 1 60); do
  pgrep -f 'rc_controller.py|rc_controlled|rc_fingerprint.py' >/dev/null || break
  sleep 1
done
if pgrep -af 'rc_controller.py|rc_controlled|rc_fingerprint.py' >> "$LOG"; then
  say "processes remain; not launching visits3"; exit 5
fi
cd "$D" || exit 6
test -f protocols/rc20261008-F-v3.json || { say "F-v3 not frozen"; exit 7; }
test ! -e controller/visits3-state.json || { say "visits3 already has state"; exit 8; }
ls evidence/fingerprints/sqlserver-sf1-visit-after.json >> "$LOG" 2>&1 && say "WARNING: visit-after fingerprint exists"
systemd-run --user --unit rc-visits3 --working-directory="$D" \
  --property=StandardOutput=append:"$D/logs/controller-visits3.out" \
  --property=StandardError=append:"$D/logs/controller-visits3.out" \
  /usr/bin/python3.12 code/rc_controller.py plans/visits3.json >> "$LOG" 2>&1
say "rc-visits3 launched (exit $?)"
