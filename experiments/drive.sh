#!/bin/sh
# Test-drive Tau with the router and planner, against the sandbox HOME (never ~/.tau).
#   experiments/drive.sh [tau args...]              Tau in the directory you call it from
#   experiments/drive.sh --fixture [tau args...]    Tau in a fresh copy of fixtures/e6
# Inside: type a goal to chat on the "budget-target" profile, or "/plan <goal>" to delegate.
WORK=$PWD
EXP=$(cd "$(dirname "$0")" && pwd)
if [ "${1:-}" = "--fixture" ]; then
  shift
  WORK=$EXP/out/drive-$(date +%H%M%S); mkdir -p "$WORK"; cp -r "$EXP/fixtures/e6/." "$WORK/"
fi
echo "workdir: $WORK   ledger: $EXP/home/.tau/ext-state/tau-router.jsonl"
# Tau discovers the tau-router installed in its venv (pip install -e ..); make_tau_home.py authorized it.
cd "$WORK" && exec env HOME="$EXP/home" "$EXP/tau-master/venv/bin/tau" "$@"
