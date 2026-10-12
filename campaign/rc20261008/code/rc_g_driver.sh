#!/usr/bin/env bash
# Phase G driver (Mac). One engine at a time:
#   start container -> record it -> load SF1 (once) -> content fingerprint must
#   equal the SF1 source -> cancellation pilot -> primary-key-only state ->
#   Q6/Q17/Q18/Q20/Q21 non-indexed -> indexes + statistics -> indexed ->
#   closing fingerprint -> stop container.
# Each completed step leaves a marker in G-mac-server/steps/; a rerun skips it.
# Stops at the first failure (marker G-mac-server/HALTED with the step name).
# Usage: nohup bash code/rc_g_driver.sh postgresql mysql oracle commercial_a > G-mac-server/driver.log 2>&1 &
set -uo pipefail
CAMP="$(cd "$(dirname "$0")/.." && pwd)"
cd "$CAMP"
OUT=G-mac-server; mkdir -p $OUT/steps evidence/fingerprints
Q="6 17 18 20 21"
# Cells censored on the benchmark host (historical SF1: all four paths > 900 s)
# have no host ratio to compare with and are not run here
# (evidence/G-scope-change-20261008.json). PostgreSQL non-indexed Q6 was
# completed in the first run directory before the change.
ni_queries() { case "$1" in postgresql) echo "18" ;; mysql) echo "6 18 21" ;; *) echo "$Q" ;; esac; }
ni_dir()     { case "$1" in postgresql) echo "postgresql-non-indexed-b" ;; *) echo "$1-non-indexed" ;; esac; }
PROTO=protocols/rc20261008-G-v1.json
SRC_FP=evidence/fingerprints/sf1-duckdb-mac-generated-v2.json
step() {   # step <id> <command...>
  local id=$1; shift
  [ -f "$OUT/steps/$id.done" ] && { echo "skip $id"; return 0; }
  echo "### $(date -u +%FT%TZ) $id"
  if bash -c "$*"; then date -u +%FT%TZ > "$OUT/steps/$id.done"; else echo "$id" > "$OUT/HALTED"; echo "HALTED at $id"; exit 1; fi
}
for E in "$@"; do
  ENV="source code/rc_g_env.sh $E"
  step "$E-start" "$ENV && \$RC_PY code/rc_g_setup.py $E start && sleep 60"
  step "$E-describe" "$ENV && \$RC_PY code/rc_g_setup.py $E describe"
  step "$E-load" "$ENV && \$RC_PY code/rc_g_setup.py $E load"
  step "$E-fp-before" "$ENV && cd \$RC_SRC && \$RC_PY \$RC_CAMPAIGN/code/rc_fingerprint.py --dbms $E --label $E-sf1-G-before --out \$RC_CAMPAIGN/evidence/fingerprints/$E-sf1-G-before.json && python3 -c \"import json;a=json.load(open('\$RC_CAMPAIGN/evidence/fingerprints/$E-sf1-G-before.json'))['content_sha256'];b=json.load(open('\$RC_CAMPAIGN/$SRC_FP'))['content_sha256'];print(a,b);assert a==b\""
  step "$E-cancel-pilot" "$ENV && \$RC_PY code/rc_g.py --campaign-dir . --run-dir $OUT/pilot-$E-cancel --protocol $PROTO --dbms $E --schema non-indexed --mode pilot --queries 1 6 --cancel-test-query 1 --cancel-check-query 6 --cancel-limit 1 && python3 -c \"import json;d=json.load(open('$OUT/pilot-$E-cancel/cancel-test/summary.json'));print(d['passed']);assert d['passed']\""
  step "$E-to-non-indexed" "$ENV && cd \$RC_SRC && \$RC_PY scripts/1-setup/manage_indexes.py --database default --action drop && \$RC_PY scripts/1-setup/manage_indexes.py --database default --action analyze && \$RC_PY scripts/1-setup/manage_indexes.py --database default --action verify --expect non-indexed"
  ND=$(ni_dir "$E"); NQ=$(ni_queries "$E")
  step "$E-run-non-indexed" "$ENV && \$RC_PY code/rc_g.py --campaign-dir . --run-dir $OUT/$ND --protocol $PROTO --dbms $E --schema non-indexed --queries $NQ || (sleep 30 && $ENV && \$RC_PY code/rc_g.py --campaign-dir . --run-dir $OUT/$ND --protocol $PROTO --dbms $E --schema non-indexed --queries $NQ --resume)"
  step "$E-verify-non-indexed" "python3 code/rc_verify.py $OUT/$ND --campaign-dir . --write"
  step "$E-to-indexed" "$ENV && cd \$RC_SRC && \$RC_PY scripts/1-setup/manage_indexes.py --database default --action create && \$RC_PY scripts/1-setup/manage_indexes.py --database default --action verify --expect indexed"
  step "$E-run-indexed" "$ENV && \$RC_PY code/rc_g.py --campaign-dir . --run-dir $OUT/$E-indexed --protocol $PROTO --dbms $E --schema indexed --queries $Q || (sleep 30 && $ENV && \$RC_PY code/rc_g.py --campaign-dir . --run-dir $OUT/$E-indexed --protocol $PROTO --dbms $E --schema indexed --queries $Q --resume)"
  step "$E-verify-indexed" "python3 code/rc_verify.py $OUT/$E-indexed --campaign-dir . --write"
  step "$E-fp-after" "$ENV && cd \$RC_SRC && \$RC_PY \$RC_CAMPAIGN/code/rc_fingerprint.py --dbms $E --label $E-sf1-G-after --out \$RC_CAMPAIGN/evidence/fingerprints/$E-sf1-G-after.json && python3 -c \"import json;a=json.load(open('\$RC_CAMPAIGN/evidence/fingerprints/$E-sf1-G-after.json'))['content_sha256'];b=json.load(open('\$RC_CAMPAIGN/$SRC_FP'))['content_sha256'];assert a==b\""
  step "$E-stop" "$ENV && \$RC_PY code/rc_g_setup.py $E stop"
done
echo "G driver complete $(date -u +%FT%TZ)"
