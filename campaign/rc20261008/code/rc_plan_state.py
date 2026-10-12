#!/usr/bin/env python3
"""Print the state of a controller plan from its events file, judged only by
the events after its latest controller_start (a resumed plan keeps the failures
of earlier attempts in the file): done | failed | running | absent.
Used by rc_switch_visits3b.sh (host) and rc_e_autostart.sh (Mac, over ssh)."""
import json
import sys
from pathlib import Path

f = Path(sys.argv[1])
if not f.exists():
    print('absent')
    sys.exit(0)
ev = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
starts = [i for i, e in enumerate(ev) if e.get('event') == 'controller_start']
tail = ev[starts[-1]:] if starts else ev
if any(e.get('event') == 'controller_done' for e in tail):
    print('done')
elif any(e.get('event') == 'step_failed' for e in tail):
    print('failed')
else:
    print('running')
