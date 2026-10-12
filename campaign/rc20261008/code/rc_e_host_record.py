#!/usr/bin/env python3
"""Phase E: the host's state for one client run, printed as JSON (run on the host
by code/rc_e_driver.sh over ssh, from stdin). Read-only."""
import json, subprocess, sys, datetime
e = sys.argv[1]
def sh(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return {'cmd': cmd, 'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
out = {'taken': datetime.datetime.now(datetime.timezone.utc).isoformat(),
       'verify': sh(['sudo', '-n', '/usr/local/sbin/bench-host', 'verify', e]),
       'oracle_process_affinity': sh(['bash', '-c', "for p in $(pgrep -u oracle); do awk '/Cpus_allowed_list/{print $2}' /proc/$p/status; done | sort | uniq -c"]) if e == 'oracle' else None,
       'active_rc_units': sh(['bash', '-c', 'systemctl --user list-units "rc-*" --no-legend --plain --state=active | grep -v "^rc-E-" || true'])['stdout'],
       'loadavg': open('/proc/loadavg').read().split()[:3],
       'wifi_link': [l.strip() for l in sh(['iw', 'dev', 'wlp3s0', 'link'])['stdout'].splitlines()
                     if l.strip().split(':')[0] in ('freq', 'signal', 'rx bitrate', 'tx bitrate')],
       'wifi_power_save': sh(['iw', 'dev', 'wlp3s0', 'get', 'power_save'])['stdout'].strip()}
print(json.dumps(out, indent=1))
