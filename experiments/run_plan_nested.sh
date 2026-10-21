#!/bin/sh
# Recursion test: the top planner must hand the whole job to ONE sub-planner. Usage: run_plan_nested.sh OUTDIR
D=$1
EXP=$(cd "$(dirname "$0")" && pwd)
rm -rf "$D"; mkdir -p "$D/work"; cp -r $EXP/fixtures/e6/. "$D/work/"; cd "$D/work"
HOME=$EXP/home timeout 1800 $EXP/tau-master/venv/bin/tau -p --mode json -ne -m claude-haiku-5-5 \
 -e tau_router.router -e tau_router.planner \
 --ext-config 'tau_router.router:profiles={"p":["claude-haiku-5-5","mistral-small","ministral-3b","nemotron-super"]}' --ext-config 'tau_router.router:profile="p"' \
 --ext-config 'tau_router.router:persona_cost=0.06' --ext-config 'tau_router.router:reserve_cost=0.0001' \
 --ext-config "tau_router.router:ledger=\"$D/ledger.jsonl\"" \
 "/plan Make 'python3 check.py' print ALL PASS by implementing the functions in durations.py, roman.py and textutil.py (do not modify check.py). Do NOT split this yourself: make exactly one delegate call with subplanner=true, model mistral-small and budget_cost 0.04, whose brief tells the sub-planner to split the work per module with its own delegate calls and check 'python3 check.py'. Then verify." > "$D/events.jsonl" 2> "$D/stderr.txt"
echo "exit=$?"; python3 check.py | tail -1
