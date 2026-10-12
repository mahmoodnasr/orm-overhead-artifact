#!/usr/bin/env python3
"""Serial step controller for campaign rc20261008 on the benchmark host.

Executes a plan (JSON list of steps) one step at a time, survives SSH loss
(launched under systemd-run --user), and records every step's command, output
tail, exit status and timestamps. A completed step is never re-run; a failed
step stops the plan (no silent continuation). A measurement step may be
resumed at most --max-resumes times, and each resume is an explicit event.

Step kinds:
  engine       sudo bench-host apply <engine>, settle, verify
  fingerprint  full-content identity of the engine's TPC-H data vs the source
  index        manage_indexes drop|create|analyze|verify on the engine
  run          rc_analytical.py (holds server.lock itself)
  verify       rc_verify.py on a run directory
  shell        a fixed command (recorded verbatim)
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402

CAMP = HERE.parent


def env_cmd(engine, kind='tpch', scale=1, extra=''):
    return f'source {HERE}/rc_env.sh {engine} {kind} {scale}; {extra}'


class Controller:
    def __init__(self, plan_path, max_resumes):
        self.plan_path = plan_path
        self.plan = json.loads(plan_path.read_text())
        self.state_path = CAMP / 'controller' / f"{self.plan['plan_id']}-state.json"
        self.events = CAMP / 'controller' / f"{self.plan['plan_id']}-events.jsonl"
        self.max_resumes = max_resumes
        self.state = C.load(self.state_path) if self.state_path.exists() else {
            'plan_id': self.plan['plan_id'], 'plan_sha256': C.file_sha256(plan_path), 'steps': {}}
        if self.state['plan_sha256'] != C.file_sha256(plan_path):
            raise SystemExit('plan file changed since this controller state was created; use a new plan_id')

    def ev(self, event_name, **kw):
        rec = {"event": event_name, "pid": os.getpid(), **C.stamps(), **kw}
        C.append_jsonl(self.events, rec)
        print(json.dumps(rec, default=str)[:600], flush=True)

    def put(self, sid, **kw):
        self.state['steps'].setdefault(sid, {}).update(kw)
        self.state['updated'] = C.stamps()
        C.save(self.state_path, self.state)

    def sh(self, cmd, log, timeout=None):
        """bash -lc so rc_env.sh can be sourced; output to a per-step log."""
        with open(log, 'ab') as fh:
            fh.write(f'\n### {C.stamps()["utc"]} $ {cmd}\n'.encode())
            fh.flush()
            p = subprocess.run(['bash', '-c', cmd], stdout=fh, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, timeout=timeout)
        tail = Path(log).read_bytes()[-3000:].decode(errors='replace')
        return p.returncode, tail

    def server_lock(self):
        fh = open(CAMP / 'server.lock', 'a+')
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh

    def step(self, s):
        sid = s['id']
        log = CAMP / 'logs' / f"{self.plan['plan_id']}-{sid}.log"
        k = s['kind']
        if k == 'engine':
            with self.server_lock():
                rc, tail = self.sh(f"sudo -n /usr/local/sbin/bench-host apply {s['engine']}", log)
                if rc != 0:
                    return rc, tail
                time.sleep(s.get('settle', 90))
                rc, tail = self.sh(f"ORACLE_SID=free sudo -n /usr/local/sbin/bench-host verify {s['engine']}", log)
                if rc != 0 and s['engine'] == 'oracle':
                    # bench-host looks for ora_pmon_FREE; this instance is 'free'.
                    # Accept only if the sole failures are the Oracle liveness/
                    # affinity lines and the processes read directly are on 0-1.
                    bad = [l for l in tail.splitlines() if '<--' in l and 'ora_*' not in l and 'oracle:' not in l]
                    rc2, aff = self.sh("for p in $(pgrep -u oracle); do awk '/Cpus_allowed_list/{print $2}' /proc/$p/status; done | sort -u", log)
                    pmon = subprocess.run(['pgrep', '-x', 'ora_pmon_free'], capture_output=True).returncode == 0
                    if not bad and aff.strip().splitlines()[-1:] == ['0-1'] and pmon:
                        return 0, tail + '\n[oracle verify accepted: only PMON-name lines failed; ora_* on 0-1]'
                return rc, tail
        if k == 'fingerprint':
            out = CAMP / 'evidence' / 'fingerprints' / f"{s['label']}.json"
            bench = s.get('benchmark', 'tpch')
            with self.server_lock():
                rc, tail = self.sh(env_cmd(s['engine'], bench, s.get('scale', 1),
                                           f"taskset -c 2,3 $RC_PY {HERE}/rc_fingerprint.py --dbms {s['engine']} "
                                           f"--benchmark {bench} --label {s['label']} --out {out}"), log)
            if rc != 0:
                return rc, tail
            got = json.loads(out.read_text())['content_sha256']
            if not s.get('expect_source'):
                return 0, f'content {got} (recorded; no comparison requested)'
            want = json.loads((CAMP / 'evidence' / 'fingerprints' / s['expect_source']).read_text())['content_sha256']
            if got != want:
                return 3, f'content {got} != source {want}'
            return 0, f'content matches source {want}'
        if k == 'index':
            acts = s['actions']
            with self.server_lock():
                for act in acts:
                    extra = '' if act != 'verify' else f" --expect {s['expect']}"
                    bench = s.get('benchmark', 'tpch')
                    rc, tail = self.sh(env_cmd(s['engine'], bench, s.get('scale', 1),
                                               f"cd {CAMP}/src && taskset -c 2,3 $RC_PY scripts/1-setup/manage_indexes.py "
                                               f"--database default --benchmark {bench} --action {act}{extra}"), log)
                    if rc != 0 or ('Warning' in tail and act in ('create', 'analyze')):
                        return rc or 4, tail
            return 0, tail
        if k == 'run':
            a = s['args']
            run_dir = CAMP / a['run_dir']
            # phases F and B subclass the phase A runner and take the same arguments
            runner = a.get('runner', 'rc_analytical.py')
            if runner not in ('rc_analytical.py', 'rc_controlled.py', 'rc_controlled2.py', 'rc_controlled3.py', 'rc_censored.py'):
                return 2, f'unknown runner {runner}'
            base = (f"cd {CAMP} && taskset -c 2,3 $RC_PY {HERE}/{runner} --campaign-dir {CAMP} "
                    f"--run-dir {run_dir} --protocol {CAMP / a['protocol']} --phase {a['phase']} "
                    f"--dbms {s['engine']} --schema {a['schema']} --scale {a.get('scale', 1)} "
                    f"--database-label {a.get('database_label', 'tpch')} --mode {a['mode']} "
                    f"--timeout {a.get('timeout', 900)} --queries {' '.join(map(str, a['queries']))}"
                    + ''.join(f' {x}' for x in a.get('extra', [])))
            resumes = self.state['steps'].get(sid, {}).get('resumes', 0)
            while True:
                resume = ' --resume' if run_dir.exists() and any(run_dir.iterdir()) else ''
                rc, tail = self.sh(env_cmd(s['engine'], 'tpch', a.get('scale', 1), base + resume), log)
                if rc == 0 or resumes >= self.max_resumes or 'gate refused' in tail or 'fatal' in tail.lower() \
                        or 'end checks failed' in tail or not s.get('resumable', True):
                    return rc, tail
                resumes += 1
                self.put(sid, resumes=resumes)
                self.ev('run_resume', step=sid, resumes=resumes, last_rc=rc, tail=tail[-800:])
                time.sleep(30)
        if k == 'tpcc':
            a = s['args']
            run_dir = CAMP / a['run_dir']
            src = CAMP / a.get('src', 'src')
            base = (f"cd {CAMP} && taskset -c 2,3 $RC_PY {HERE}/rc_tpcc.py --campaign-dir {CAMP} --src {src} --run-dir {run_dir} "
                    f"--protocol {CAMP / a['protocol']} --phase {a['phase']} --dbms {s['engine']} --schema {a['schema']} "
                    f"--blocks {a.get('blocks', 24)} --mode {a['mode']} --transactions {' '.join(map(str, a.get('transactions', [1, 2, 3, 4, 5])))}")
            resumes = self.state['steps'].get(sid, {}).get('resumes', 0)
            while True:
                resume = ' --resume' if run_dir.exists() and any(run_dir.iterdir()) else ''
                rc, tail = self.sh(f"export RC_SRCDIR={src}; " + env_cmd(s['engine'], 'tpcc', 1, base + resume), log)
                if rc == 0 or resumes >= self.max_resumes or 'revert' in tail or 'counts moved' in tail \
                        or 'end checks failed' in tail:
                    return rc, tail
                resumes += 1
                self.put(sid, resumes=resumes)
                self.ev('run_resume', step=sid, resumes=resumes, last_rc=rc, tail=tail[-800:])
                time.sleep(30)
        if k == 'verify':
            rc, tail = self.sh(f"{sys.executable} {HERE}/rc_verify.py {CAMP / s['run_dir']} --campaign-dir {CAMP} --write", log)
            return rc, tail
        if k == 'shell':
            return self.sh(s['command'], log)
        return 9, f'unknown step kind {k}'

    def go(self):
        lockfh = open(CAMP / 'controller' / 'controller.lock', 'a+')
        fcntl.flock(lockfh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.ev('controller_start', plan=self.plan['plan_id'], steps=[s['id'] for s in self.plan['steps']])
        for s in self.plan['steps']:
            st = self.state['steps'].get(s['id'], {})
            if st.get('status') == 'done':
                continue
            self.put(s['id'], status='running', started=C.stamps(), spec=s)
            self.ev('step_start', step=s['id'], kind=s['kind'])
            t0 = time.monotonic()
            try:
                rc, tail = self.step(s)
            except Exception as exc:
                rc, tail = 8, repr(exc)
            secs = round(time.monotonic() - t0, 1)
            if rc == 0:
                self.put(s['id'], status='done', finished=C.stamps(), seconds=secs, tail=tail[-1500:])
                self.ev('step_done', step=s['id'], seconds=secs)
            else:
                self.put(s['id'], status='failed', finished=C.stamps(), seconds=secs, rc=rc, tail=tail[-3000:])
                self.ev('step_failed', step=s['id'], rc=rc, seconds=secs, tail=tail[-1500:])
                self.state['halted'] = {'step': s['id'], **C.stamps()}
                C.save(self.state_path, self.state)
                return 1
        self.state['finished'] = C.stamps()
        C.save(self.state_path, self.state)
        self.ev('controller_done', plan=self.plan['plan_id'])
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('plan', type=Path)
    ap.add_argument('--max-resumes', type=int, default=2)
    a = ap.parse_args()
    (CAMP / 'controller').mkdir(exist_ok=True)
    (CAMP / 'logs').mkdir(exist_ok=True)
    sys.exit(Controller(a.plan.resolve(), a.max_resumes).go())


if __name__ == '__main__':
    main()
