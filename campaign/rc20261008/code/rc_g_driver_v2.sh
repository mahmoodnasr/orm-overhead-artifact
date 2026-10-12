#!/bin/bash
# Phase G v2 driver (Mac). Database container on VM vCPUs 0-1 (2 CPUs, 3 GB,
# no swap); client container (Python 3.12.3, host's package versions) on vCPUs
# 2-3 - the host's split. One engine at a time. Host-censored cells are not
# run (evidence/G-scope-change-20261008.json). Markers in G-mac-server/v2/steps.
# Usage: nohup /bin/bash code/rc_g_driver_v2.sh postgresql mysql oracle commercial_a > G-mac-server/v2/driver.log 2>&1 &
set -uo pipefail
CAMP="$(cd "$(dirname "$0")/.." && pwd)"; cd "$CAMP"
SRC="$HOME/rc20261008-client/src"
OUT=G-mac-server/v2; mkdir -p $OUT/steps evidence/fingerprints
Q="6 17 18 20 21"
PROTO=protocols/rc20261008-G-v2.json
SRC_FP=evidence/fingerprints/sf1-duckdb-mac-generated-v2.json
ni_queries() { case "$1" in postgresql) echo "6 18" ;; mysql) echo "6 18 21" ;; *) echo "$Q" ;; esac; }
step() {
  local id=$1; shift
  [ -f "$OUT/steps/$id.done" ] && { echo "skip $id"; return 0; }
  echo "### $(date -u +%FT%TZ) $id"
  if /bin/bash -c "$*"; then date -u +%FT%TZ > "$OUT/steps/$id.done"; else echo "$id" > "$OUT/HALTED"; echo "HALTED at $id"; exit 1; fi
}
client() {  # client <engine> <python args...>: runs in the pinned client container
  local e=$1; shift
  local rec; rec=$(source code/rc_g_env.sh "$e" >/dev/null 2>&1; "$HOME/rc20261008-client/venv/bin/python" code/rc_g_setup.py "$e" record | tail -1)
  docker run --rm --name rcg-client --cpuset-cpus 2,3 --cpus 2 --memory 3g --memory-swap 3g --network rcg-net \
    -e RC_G_CONTAINER_JSON="$rec" -e RC_SRC="$SRC" -v "$CAMP:$CAMP" -v "$SRC:$SRC" -w "$CAMP" rcg-client:3.12.3 \
    bash -c "source code/rc_g_env.sh $e container && python code/rc_g.py --campaign-dir $CAMP --src $SRC --protocol $PROTO --dbms $e --client-cpus 2,3 $*"
}
export -f client; export CAMP SRC PROTO
for E in "$@"; do
  ENV="source code/rc_g_env.sh $E"
  NQ=$(ni_queries "$E")
  step "$E-start" "$ENV && \$RC_PY code/rc_g_setup.py $E start && \$RC_PY code/rc_g_setup.py $E network && sleep 30"
  step "$E-describe" "$ENV && \$RC_PY code/rc_g_setup.py $E describe"
  step "$E-load" "$ENV && \$RC_PY code/rc_g_setup.py $E load"
  step "$E-fp-before" "$ENV && cd \$RC_SRC && \$RC_PY \$RC_CAMPAIGN/code/rc_fingerprint.py --dbms $E --label $E-sf1-Gv2-before --out \$RC_CAMPAIGN/evidence/fingerprints/$E-sf1-Gv2-before.json && python3 -c \"import json;a=json.load(open('\$RC_CAMPAIGN/evidence/fingerprints/$E-sf1-Gv2-before.json'))['content_sha256'];b=json.load(open('\$RC_CAMPAIGN/$SRC_FP'))['content_sha256'];print(a,b);assert a==b\""
  step "$E-to-non-indexed" "$ENV && cd \$RC_SRC && \$RC_PY scripts/1-setup/manage_indexes.py --database default --action drop && \$RC_PY scripts/1-setup/manage_indexes.py --database default --action analyze && \$RC_PY scripts/1-setup/manage_indexes.py --database default --action verify --expect non-indexed"
  # a fresh directory per attempt: an earlier refused or failed attempt stays as evidence
  step "$E-cancel-pilot" "PD=$OUT/pilot-$E-cancel-\$(date -u +%H%M%S); client $E --run-dir \$PD --schema non-indexed --mode pilot --queries 1 6 --cancel-test-query 1 --cancel-check-query 6 --cancel-limit 1 && python3 -c \"import json;d=json.load(open('\$PD/cancel-test/summary.json'));print(d['passed']);assert d['passed']\""
  step "$E-run-non-indexed" "client $E --run-dir $OUT/$E-non-indexed --schema non-indexed --queries $NQ || (sleep 30; client $E --run-dir $OUT/$E-non-indexed --schema non-indexed --queries $NQ --resume)"
  step "$E-verify-non-indexed" "python3 code/rc_verify.py $OUT/$E-non-indexed --campaign-dir . --write"
  step "$E-to-indexed" "$ENV && cd \$RC_SRC && \$RC_PY scripts/1-setup/manage_indexes.py --database default --action create && \$RC_PY scripts/1-setup/manage_indexes.py --database default --action verify --expect indexed"
  step "$E-run-indexed" "client $E --run-dir $OUT/$E-indexed --schema indexed --queries $Q || (sleep 30; client $E --run-dir $OUT/$E-indexed --schema indexed --queries $Q --resume)"
  step "$E-verify-indexed" "python3 code/rc_verify.py $OUT/$E-indexed --campaign-dir . --write"
  step "$E-fp-after" "$ENV && cd \$RC_SRC && \$RC_PY \$RC_CAMPAIGN/code/rc_fingerprint.py --dbms $E --label $E-sf1-Gv2-after --out \$RC_CAMPAIGN/evidence/fingerprints/$E-sf1-Gv2-after.json && python3 -c \"import json;a=json.load(open('\$RC_CAMPAIGN/evidence/fingerprints/$E-sf1-Gv2-after.json'))['content_sha256'];b=json.load(open('\$RC_CAMPAIGN/$SRC_FP'))['content_sha256'];assert a==b\""
  step "$E-stop" "$ENV && \$RC_PY code/rc_g_setup.py $E stop"
done
echo "G v2 driver complete $(date -u +%FT%TZ)"
