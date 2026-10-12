#!/bin/bash
# Censored-cell validation driver (Mac, protocol rc20261008-V-v1; R1-2).
# Same containers, data and client container as phase G v2. Per engine:
# start -> record -> content fingerprint must equal the SF1 source ->
# primary-key-only state -> validation run (14340 s cap per call, protocol V-v2) -> closing
# fingerprint -> stop. Markers in V-censored/steps; a rerun skips done steps
# and the runner resumes per cell. Stops at the first failure (V-censored/HALTED).
# Usage: nohup /bin/bash code/rc_v_driver.sh postgresql mysql >> V-censored/driver.log 2>&1 &
set -uo pipefail
CAMP="$(cd "$(dirname "$0")/.." && pwd)"; cd "$CAMP"
SRC="$HOME/rc20261008-client/src"
OUT=V-censored; mkdir -p $OUT/steps evidence/fingerprints
PROTO=protocols/rc20261008-V-v2.json
SRC_FP=evidence/fingerprints/sf1-duckdb-mac-generated-v2.json
queries() { case "$1" in postgresql) echo "13 17 20 21" ;; mysql) echo "13 17 20" ;; esac; }
step() {
  local id=$1; shift
  [ -f "$OUT/steps/$id.done" ] && { echo "skip $id"; return 0; }
  echo "### $(date -u +%FT%TZ) $id"
  if /bin/bash -c "$*"; then date -u +%FT%TZ > "$OUT/steps/$id.done"; else echo "$id" > "$OUT/HALTED"; echo "HALTED at $id"; exit 1; fi
}
client() {  # client <engine> <args...>: the validation runner in the pinned client container
  local e=$1; shift
  local rec; rec=$(source code/rc_g_env.sh "$e" >/dev/null 2>&1; "$HOME/rc20261008-client/venv/bin/python" code/rc_g_setup.py "$e" record | tail -1)
  docker run --rm --name rcg-client --cpuset-cpus 2,3 --cpus 2 --memory 3g --memory-swap 3g --network rcg-net \
    -e RC_G_CONTAINER_JSON="$rec" -e RC_SRC="$SRC" -v "$CAMP:$CAMP" -v "$SRC:$SRC" -w "$CAMP" rcg-client:3.12.3 \
    bash -c "source code/rc_g_env.sh $e container && python code/rc_validate_censored.py --campaign-dir $CAMP --src $SRC --protocol $PROTO --dbms $e --client-cpus 2,3 --timeout 14340 $*"
}
fp() {  # fp <engine> <label>: content fingerprint, must equal the SF1 source
  echo "source code/rc_g_env.sh $1 && cd \$RC_SRC && \$RC_PY \$RC_CAMPAIGN/code/rc_fingerprint.py --dbms $1 --label $1-sf1-$2 --out \$RC_CAMPAIGN/evidence/fingerprints/$1-sf1-$2.json && python3 -c \"import json;a=json.load(open('\$RC_CAMPAIGN/evidence/fingerprints/$1-sf1-$2.json'))['content_sha256'];b=json.load(open('\$RC_CAMPAIGN/$SRC_FP'))['content_sha256'];print(a,b);assert a==b\""
}
export -f client; export CAMP SRC PROTO
for E in "$@"; do
  ENV="source code/rc_g_env.sh $E"
  step "$E-start" "$ENV && \$RC_PY code/rc_g_setup.py $E start && \$RC_PY code/rc_g_setup.py $E network && sleep 30"
  step "$E-describe" "$ENV && \$RC_PY code/rc_g_setup.py $E describe"
  step "$E-fp-before" "$(fp $E V-before)"
  step "$E-to-non-indexed" "$ENV && cd \$RC_SRC && \$RC_PY scripts/1-setup/manage_indexes.py --database default --action drop && \$RC_PY scripts/1-setup/manage_indexes.py --database default --action analyze && \$RC_PY scripts/1-setup/manage_indexes.py --database default --action verify --expect non-indexed"
  step "$E-validate" "client $E --run-dir $OUT/v2/$E-non-indexed --queries $(queries $E) || (sleep 30; client $E --run-dir $OUT/v2/$E-non-indexed --queries $(queries $E) --resume)"
  step "$E-fp-after" "$(fp $E V-after)"
  step "$E-stop" "$ENV && \$RC_PY code/rc_g_setup.py $E stop"
done
echo "V driver complete $(date -u +%FT%TZ)"
