#!/bin/sh
# Persistence under downgrade. Usage: run_e4.sh REPLICATE
R=$1
EXP=$(cd "$(dirname "$0")" && pwd)
PY=$EXP/../venv/bin/python
GOAL="Implement every function in solution.py so that 'python3 check.py' prints ALL PASS. Run it after each change and fix what fails. Do not modify check.py. Keep working until every check passes, then reply DONE."
SCORE="python3 check.py | grep -E 'passed'"
run() { name=$1; shift; $PY $EXP/persona_host.py $EXP/out/e4/$name-$R --seed $EXP/fixtures/e4 --score "$SCORE" --goal "$GOAL" "$@" > $EXP/out/e4/$name-$R.log 2>&1; }
mkdir -p $EXP/out/e4
run A-haiku --model haiku --ext 'ladder=["haiku"]' &
run B-small --model ministral-3b --ext 'ladder=["ministral-3b"]' &
run C-handoff --model haiku --ext 'ladder=["haiku","ministral-3b"]' --ext 'budgets={"anthropic":{"usd":0.0003,"period":"once","since":0}}' --ext 'reserve_usd=0.0001' &
run D-bare --model haiku --ext 'ladder=["haiku","ministral-3b"]' --ext 'budgets={"anthropic":{"usd":0.0003,"period":"once","since":0}}' --ext 'reserve_usd=0.0001' --ext 'handoff=false' &
wait
