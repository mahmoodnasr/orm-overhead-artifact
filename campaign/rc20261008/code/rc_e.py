#!/usr/bin/env python3
"""Phase E runner: the phase A protocol with the client on a physically
separate machine (this Mac), the databases on the benchmark host, over the
LAN (Wi-Fi at both ends; no wired adapter).

Identical measurement and result checks to phase A: it is the phase A runner,
subclassed, with --client-mode separate-client, on the same database host,
SF1 data, source snapshot, inputs, index states and server settings. The
runner's own gate checks the database state over SQL as in phase A (row
counts, secondary indexes, parallelism limit, PostgreSQL parallel workers, Oracle result
cache, source and runner hashes). What changes is the evidence the
same-host runner reads locally:

- The host's own state (bench-host verify: governor, turbo, SMT, CPUs, the
  engine's cgroup) cannot be read from the client. The driver reads it over
  ssh immediately before the run and passes the record in RC_E_HOST_VERIFY;
  this runner records it as host_verification, so phase A's gate applies to
  it unchanged, and refuses to run without one. The driver records it again
  after the run.
- Oracle: when V$SESSION is not readable, phase A proves a cancelled
  statement stopped by sampling Oracle's processes in /proc. On the client
  there are none to sample, so that fallback would report "stopped"
  unconditionally. This runner refuses Oracle unless V$SESSION is readable
  (root helper action oracle-session-view); the V$SESSION path was exercised
  on 2026-10-09 (three forced timeouts, all verified stopped).
- The client runs in the pinned client container of phase G v2 (Python
  3.12.3 and the host's package versions, 2 CPUs, 3 GB): the container's
  cgroup and the Mac's model are recorded, and the limits are gated.

Network conditions (RTT, jitter, loss, Wi-Fi link) are logged by the driver
around and during every run; they are not part of a record's timing.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402
from rc_analytical import Runner  # noqa: E402

DB_HOST = '<host-ip>'


class RemoteClient(Runner):
    def inventory(self, label):
        inv = super().inventory(label)
        inv['code_hashes']['rc_e.py'] = C.file_sha256(HERE / 'rc_e.py')
        hv = os.environ.get('RC_E_HOST_VERIFY')
        if hv and Path(hv).exists():
            j = json.loads(Path(hv).read_text())
            inv['host_verification'] = j.get('verify')
            inv['oracle_process_affinity'] = j.get('oracle_process_affinity')
            inv['host_record'] = {'file': hv, 'sha256': C.file_sha256(hv), 'taken': j.get('taken'),
                                  'note': 'read over ssh by the driver immediately before this run'}
        else:
            inv['host_verification'] = None
            inv['host_record'] = {'missing': hv}
        cl = {}
        for k, path in (('cpus_allowed', '/proc/self/status'), ('cpu_max', '/sys/fs/cgroup/cpu.max'),
                        ('memory_max', '/sys/fs/cgroup/memory.max'), ('cpuset', '/sys/fs/cgroup/cpuset.cpus.effective')):
            try:
                t = Path(path).read_text()
                cl[k] = [l.split()[-1] for l in t.splitlines() if l.startswith('Cpus_allowed_list')][0] \
                    if k == 'cpus_allowed' else t.strip()
            except Exception:
                cl[k] = None
        inv['client_container'] = cl
        mj = os.environ.get('RC_E_CLIENT_JSON')
        inv['client_machine'] = json.loads(Path(mj).read_text()) if mj and Path(mj).exists() else {'missing': mj}
        inv['client_platform'] = {'machine': platform.machine(), 'platform': platform.platform()}
        inv['database_address'] = DB_HOST
        if self.a.dbms == 'oracle':
            try:
                inv['oracle_v_session'] = self._dj_query(
                    "SELECT COUNT(*) AS n FROM v$session WHERE sid = SYS_CONTEXT('USERENV','SID')")
            except Exception as exc:
                inv['oracle_v_session'] = {'error': str(exc)[:300]}
        return inv

    def gate(self, inv):
        problems = super().gate(inv)
        if self.a.client_mode != 'separate-client':
            problems.append(f'client mode {self.a.client_mode}, not separate-client')
        if not inv.get('host_verification'):
            problems.append('no host verification record (RC_E_HOST_VERIFY) taken before the run')
        mj = inv.get('client_machine') or {}
        if 'missing' in mj:
            problems.append('no client machine record (RC_E_CLIENT_JSON)')
        cl = inv.get('client_container') or {}
        if cl.get('cpu_max') != '200000 100000' or cl.get('memory_max') != str(3 * 1024 ** 3):
            problems.append(f'client container limits differ from 2 CPU / 3 GB: {cl}')
        if self.a.dbms == 'oracle':
            v = inv.get('oracle_v_session')
            if not (isinstance(v, list) and v and int(v[0]['n']) == 1):
                problems.append(f'Oracle V$SESSION not readable ({v}); cancellation could not be verified '
                                'from the client (root helper action oracle-session-view)')
        return problems


def main():
    ap = argparse.ArgumentParser()
    for x in ('--campaign-dir', '--run-dir', '--protocol'):
        ap.add_argument(x, type=Path, required=True)
    ap.add_argument('--src', type=Path, default=Path.home() / 'rc20261008-client' / 'src')
    ap.add_argument('--phase', default='E')
    ap.add_argument('--dbms', required=True, choices=['postgresql', 'mysql', 'oracle', 'sqlserver'])
    ap.add_argument('--schema', required=True, choices=['indexed', 'non-indexed'])
    ap.add_argument('--scale', type=int, default=1)
    ap.add_argument('--database-label', default='tpch')
    ap.add_argument('--queries', type=int, nargs='+', required=True)
    ap.add_argument('--timeout', type=float, default=900)
    ap.add_argument('--blocks', type=int, default=8)
    ap.add_argument('--mode', choices=['main', 'pilot'], default='main')
    ap.add_argument('--client-mode', default='separate-client')
    ap.add_argument('--client-cpus', default='')
    ap.add_argument('--cancel-wait', type=float, default=60)
    ap.add_argument('--crash-at', type=int, default=0)
    ap.add_argument('--cancel-test-query', type=int, default=0)
    ap.add_argument('--cancel-check-query', type=int, default=6)
    ap.add_argument('--cancel-limit', type=float, default=1)
    ap.add_argument('--resume', action='store_true')
    a = ap.parse_args()
    if a.cancel_test_query and a.mode != 'pilot':
        raise SystemExit('the cancellation test is pilot evidence only')
    RemoteClient(a).main()


if __name__ == '__main__':
    main()
