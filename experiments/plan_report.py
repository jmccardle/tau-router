"""Summarize a planner run: router accounts and switches, spend per cursor, and each delegate outcome.

    python experiments/plan_report.py experiments/out/p3
"""

import collections
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
rows = [json.loads(line) for line in (out / "ledger.jsonl").read_text().splitlines()]
for r in rows:
    if r["kind"] not in ("usage", "account"):
        r.pop("ts")
        print("ROUTER", r)
cells: dict[str, list] = collections.defaultdict(lambda: [0, 0.0, set()])
for r in rows:
    if r["kind"] == "usage":
        cell = cells[r["cursor"]]
        cell[0] += 1
        cell[1] += r.get("cost", r.get("usd")) or 0  # "usd" in runs before 0.1
        cell[2].add(r["model"])
for cursor, (n, cost, models) in cells.items():
    print(f"CURSOR {cursor} {n:3d} calls {cost:.5f} {sorted(models)}")
print(f"TOTAL ${sum(c[1] for c in cells.values()):.5f}")
for line in (out / "events.jsonl").read_text().splitlines():
    e = json.loads(line)
    if e.get("type") == "tool_execution_end" and e.get("tool_name") == "delegate":
        result = e.get("result")
        blocks = result["content"] if isinstance(result, dict) else result
        text = blocks[0]["text"] if isinstance(blocks, list) else str(blocks)
        try:
            r = json.loads(text)
        except json.JSONDecodeError:
            print("DELEGATE (error)", text[:200])
            continue
        attempts = [(a["model"], a["check_passed"], a.get("spent", a.get("spent_usd"))) for a in r["attempts"]]
        print(f"DELEGATE {r['task_id']:10} passed={r['passed']} attempts={attempts} left={r.get('your_budget_left', r.get('your_budget_left_usd'))}")
