#!/usr/bin/env python3
"""Phase E: the client Mac's hardware and software for a run inventory
(model, CPU, memory, macOS, Docker, client image digest, power). No serial
number or hardware UUID."""
import json, platform, subprocess, sys
def s(*c): return subprocess.run(list(c), capture_output=True, text=True).stdout.strip()
img = s('docker', 'image', 'inspect', 'rcg-client:3.12.3', '--format', '{{json .}}')
j = json.loads(img) if img else {}
out = {'model': s('sysctl', '-n', 'hw.model'), 'cpu': s('sysctl', '-n', 'machdep.cpu.brand_string'),
       'cores': s('sysctl', '-n', 'hw.ncpu'), 'memory_bytes': s('sysctl', '-n', 'hw.memsize'),
       'perflevels': [s('sysctl', '-n', f'hw.perflevel{i}.logicalcpu') for i in (0, 1)],
       'macos': platform.mac_ver()[0], 'docker_server': s('docker', 'version', '--format', '{{.Server.Version}}'),
       'client_image': {'id': j.get('Id'), 'repo_digests': j.get('RepoDigests'), 'architecture': j.get('Architecture')},
       'power': s('pmset', '-g', 'batt').splitlines()[:1]}
json.dump(out, open(sys.argv[1], 'w'), indent=1)
