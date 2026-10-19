#!/bin/sh
# Planner on Tau master. Usage: run_plan.sh OUTDIR PLANNER_MODEL PERSONA_COST [extra tau args...]
D=$1; M=$2; COST=$3; shift 3
EXP=$(cd "$(dirname "$0")" && pwd)
rm -rf "$D"; mkdir -p "$D/work"; cp -r $EXP/fixtures/e6/. "$D/work/"; cd "$D/work"
HOME=$EXP/home timeout 1500 $EXP/tau-master/venv/bin/tau -p --mode json -ne -m "$M" \
 $($EXP/tau-master/venv/bin/tau-router ext-args) \
 --ext-config 'router.profiles={"p":["claude-haiku-5-5","mistral-small","ministral-3b","nemotron-super"]}' --ext-config 'router.profile="p"' \
 --ext-config "router.persona_cost=$COST" --ext-config 'router.reserve_cost=0.0001' \
 --ext-config "router.ledger=\"$D/ledger.jsonl\"" "$@" \
 "/plan Make 'python3 check.py' print ALL PASS by implementing the functions in durations.py, roman.py and textutil.py. Do not modify check.py. Each module can be checked alone with 'python3 check.py <module>'." > "$D/events.jsonl" 2> "$D/stderr.txt"
echo "exit=$?"; python3 check.py | tail -1
