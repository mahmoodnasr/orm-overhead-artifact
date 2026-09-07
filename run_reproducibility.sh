#!/usr/bin/env bash
# SUPERSEDED. This script describes a pipeline that no longer exists.
#
# It calls scripts/1-setup/generate_tpch_data.sh and load_data_*.sh, which are
# now in scripts/superseded/ because they build and read .tbl files the pipeline
# stopped producing when data generation moved to DuckDB. Running it will fail
# at the first step.
#
# The path that was actually used is in REPRODUCE.md, and every command there was
# run to produce results/all_results.csv.
echo "This script is superseded. See REPRODUCE.md for the working path." >&2
echo "Kept because the paper and the earlier READMEs refer to it by name." >&2
exit 1
