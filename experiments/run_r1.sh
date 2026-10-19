#!/bin/sh
# Router v0 on Tau master, one process. Usage: run_r1.sh OUTDIR [extra --ext-config args...]
D=$1; shift
EXP=$(cd "$(dirname "$0")" && pwd)
rm -rf "$D"; mkdir -p "$D/work"; cd "$D/work"
HOME=$EXP/home timeout 900 $EXP/tau-master/venv/bin/tau -p --mode json -ne -m haiku -e $EXP/ext/router.py \
 --ext-config 'router.profiles={"budget-target":["haiku","mistral-small","ministral-3b"]}' --ext-config 'router.profile="budget-target"' \
 --ext-config 'router.budgets={"anthropic":{"usd":0.0005,"period":"once","since":0}}' --ext-config 'router.reserve_usd=0.0001' \
 --ext-config "router.ledger=\"$D/ledger.jsonl\"" "$@" "$(cat $EXP/out/e3/prompt.txt)" > "$D/events.jsonl" 2> "$D/stderr.txt"
echo "exit=$?"
