#!/bin/sh
# Usage: run_e3.sh OUTDIR START_MODEL ANTHROPIC_USD HANDOFF LADDER_JSON
set -e
OUT=$1; MODEL=$2; USD=$3; HANDOFF=$4; LADDER=$5
EXP=$(cd "$(dirname "$0")" && pwd)
rm -rf "$OUT"; mkdir -p "$OUT/work"; cd "$OUT/work"
HOME=$EXP/home timeout 900 "${TAU_BIN:-tau}" -p --mode json -ne -m "$MODEL" -e "$EXP/ext/governor.py" \
 --ext-config "governor.ladder=$LADDER" \
 --ext-config "governor.budgets={\"anthropic\":{\"usd\":$USD,\"period\":\"once\",\"since\":0}}" \
 --ext-config 'governor.reserve_usd=0.0001' \
 --ext-config "governor.handoff=$HANDOFF" \
 --ext-config "governor.ledger=\"$OUT/ledger.jsonl\"" \
 "$(cat "$OUT/../prompt.txt")" > "$OUT/events.jsonl" 2> "$OUT/stderr.txt" || echo "tau exit $?" >> "$OUT/stderr.txt"
