#!/bin/sh
# Agent-chosen models under a persona budget. Usage: run_e5.sh REPLICATE START_MODEL
R=$1; START=${2:-mistral-small}
EXP=$(cd "$(dirname "$0")" && pwd)
GOAL="You are a persistent agent with a total budget of \$0.02 for this whole job, shared by every model you run on. You can see your spending with budget_status and change the model that runs you with select_model (effective after the current step). Larger models cost more per token, smaller ones may need more attempts. Do three tasks, in order:
1. Write the value of 17*23 into answer.txt.
2. Implement every function in solution.py so that 'python3 check.py' prints ALL PASS (do not modify check.py).
3. Write a three-line poem about thrift into poem.txt.
Before each task, check budget_status and pick the cheapest model you believe will do that task well. At the end, write report.txt listing, per task, the model you used and why, and reply DONE."
mkdir -p $EXP/out/e5
$EXP/../venv/bin/python $EXP/persona_host.py $EXP/out/e5/$START-$R --seed $EXP/fixtures/e4 --max-rounds 12 \
  --score "python3 check.py | grep passed; cat answer.txt; echo; cat report.txt" --goal "$GOAL" --model $START \
  --ext 'mode="agent"' --ext 'ladder=["haiku","mistral-small","ministral-3b","nemotron-super"]' \
  --ext 'persona_usd=0.02' > $EXP/out/e5/$START-$R.log 2>&1
