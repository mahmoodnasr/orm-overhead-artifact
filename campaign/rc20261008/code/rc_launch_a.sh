#!/usr/bin/env bash
# Freeze protocol rc20261008-A-v1, write the phase A plan, launch its controller
# under systemd --user. Run on the benchmark host from the campaign directory,
# after every pilot plan has finished. Refuses if a protocol or plan exists.
set -euo pipefail
cd <campaign>
test ! -e protocols/rc20261008-A-v1.json
test ! -e plans/A-sf1.json
! systemctl --user is-active -q rc-chain-P-rest
source code/rc_env.sh sqlserver >/dev/null
$RC_PY code/rc_freeze.py --campaign-dir . --protocol-id rc20261008-A-v1 --phase A \
  --historical-measurements <source-repo>/results/sf1/measurements \
  --fingerprint evidence/fingerprints/sf1-duckdb-mac-generated-v2.json \
  --fingerprint evidence/fingerprints/sf2-duckdb-source-v2.json \
  --policy rc20261008-results-v3 \
  --notes "Main analytical protocol for phases A (SF1, 352 cells) and D (SF2 subset). Result policy v3. 900 s per call; no 2700 s retry. Runner code frozen by hash."
$RC_PY code/rc_make_plan_a.py --protocol protocols/rc20261008-A-v1.json --protocol-file protocols/rc20261008-A-v1.json \
  --engines oracle mysql postgresql sqlserver --out plans/A-sf1.json
systemd-run --user --unit rc-A-sf1 --working-directory="$PWD" \
  --property=StandardOutput=append:"$PWD/logs/controller-A-sf1.out" \
  --property=StandardError=append:"$PWD/logs/controller-A-sf1.out" \
  /usr/bin/python3.12 code/rc_controller.py plans/A-sf1.json
sha256sum protocols/rc20261008-A-v1.json plans/A-sf1.json code/rc_analytical.py code/rc_common.py
