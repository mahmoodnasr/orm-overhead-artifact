#!/usr/bin/env python3
"""Phase G runner: the phase A protocol on the second server (this Mac).

Identical measurement and result checks to phase A (it is the phase A runner,
subclassed). What differs is only the environment evidence: there is no
bench-host on this machine, so each inventory records the container instead -
image and digest, image and host architecture, CPU and memory limits - and
the Mac's model and macOS version. The engine is limited to 2 CPUs and 3 GB
like the host's cgroup.

v2 (protocol G-v2): the client runs in its own container pinned to two other
VM vCPUs (as the host pins the client to CPUs 2-3), Python 3.12.3 like the
host. Inside it there is no Docker CLI, so the driver writes the inspection of
the database container and of every running container to RC_G_CONTAINER_JSON
just before the run, and this runner records the client container's own
cpuset and memory limit from its cgroup.
"""
import os
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc_common as C  # noqa: E402
from rc_analytical import Runner  # noqa: E402


class SecondServer(Runner):
    def inventory(self, label):
        inv = super().inventory(label)
        inv['code_hashes']['rc_g.py'] = C.file_sha256(HERE / 'rc_g.py')
        name = f'rcg-{self.a.dbms}'
        jf = os.environ.get('RC_G_CONTAINER_JSON')
        try:
            if jf:
                j = json.loads(Path(jf).read_text())
                inv['container'], inv['containers_running'] = j['container'], j['containers_running']
                inv['container_record'] = {'file': jf, 'sha256': C.file_sha256(jf)}
            else:
                d = json.loads(subprocess.run(['docker', 'inspect', name], capture_output=True, text=True).stdout)[0]
                img = json.loads(subprocess.run(['docker', 'image', 'inspect', d['Image']], capture_output=True, text=True).stdout)[0]
                inv['container'] = {'name': name, 'image': d['Config']['Image'], 'repo_digests': img.get('RepoDigests'),
                                    'image_architecture': img.get('Architecture'), 'nano_cpus': d['HostConfig'].get('NanoCpus'),
                                    'cpuset_cpus': d['HostConfig'].get('CpusetCpus'), 'memory': d['HostConfig'].get('Memory'),
                                    'memory_swap': d['HostConfig'].get('MemorySwap'), 'cmd': d['Config'].get('Cmd'),
                                    'running': d['State'].get('Running')}
                stats = subprocess.run(['docker', 'stats', '--no-stream', '--format', '{{json .}}'],
                                       capture_output=True, text=True).stdout.splitlines()
                inv['containers_running'] = [json.loads(x) for x in stats if x.strip()]
        except Exception as exc:
            inv['container'] = {'error': repr(exc)}
        cl = {}
        for k, path in (('cpus_allowed', '/proc/self/status'), ('cpu_max', '/sys/fs/cgroup/cpu.max'),
                        ('memory_max', '/sys/fs/cgroup/memory.max'), ('cpuset', '/sys/fs/cgroup/cpuset.cpus.effective')):
            try:
                t = Path(path).read_text()
                cl[k] = [l.split()[-1] for l in t.splitlines() if l.startswith('Cpus_allowed_list')][0] if k == 'cpus_allowed' else t.strip()
            except Exception:
                cl[k] = None
        inv['client_container'] = cl
        inv['mac'] = {'cpu': subprocess.run(['sysctl', '-n', 'machdep.cpu.brand_string'], capture_output=True, text=True).stdout.strip(),
                      'macos': platform.mac_ver()[0], 'machine': platform.machine()}
        return inv

    def gate(self, inv):
        problems = super().gate(inv)
        c = inv.get('container', {})
        if not c.get('running'):
            problems.append('container not running')
        if c.get('nano_cpus') != 2_000_000_000 or c.get('memory') != 3 * 1024 ** 3 or c.get('memory_swap') != 3 * 1024 ** 3:
            problems.append(f'container limits differ from the 2 CPU / 3 GB envelope: {c}')
        others = [x.get('Name') for x in inv.get('containers_running', [])
                  if x.get('Name') not in (f'rcg-{self.a.dbms}', 'rcg-client')]
        if others:
            problems.append(f'other containers running in the VM: {others}')
        return problems


def main():
    ap = argparse.ArgumentParser()
    for x in ('--campaign-dir', '--run-dir', '--protocol'):
        ap.add_argument(x, type=Path, required=True)
    ap.add_argument('--src', type=Path, default=Path.home() / 'rc20261008-client' / 'src')
    ap.add_argument('--phase', default='G')
    ap.add_argument('--dbms', required=True, choices=['postgresql', 'mysql', 'oracle', 'sqlserver'])
    ap.add_argument('--schema', required=True, choices=['indexed', 'non-indexed'])
    ap.add_argument('--scale', type=int, default=1)
    ap.add_argument('--database-label', default='mac-tpch')
    ap.add_argument('--queries', type=int, nargs='+', required=True)
    ap.add_argument('--timeout', type=float, default=900)
    ap.add_argument('--blocks', type=int, default=8)
    ap.add_argument('--mode', choices=['main', 'pilot'], default='main')
    ap.add_argument('--client-mode', default='second-server-mac')
    ap.add_argument('--client-cpus', default='')
    ap.add_argument('--cancel-wait', type=float, default=60)
    ap.add_argument('--crash-at', type=int, default=0)
    ap.add_argument('--cancel-test-query', type=int, default=0)
    ap.add_argument('--cancel-check-query', type=int, default=6)
    ap.add_argument('--cancel-limit', type=float, default=1)
    ap.add_argument('--resume', action='store_true')
    a = ap.parse_args()
    SecondServer(a).main()


if __name__ == '__main__':
    main()
