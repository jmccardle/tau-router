"""Print a run's ledger and the assistant's text/tool calls, in order."""
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
for l in (out / "ledger.jsonl").read_text().splitlines() if (out / "ledger.jsonl").exists() else []:
    r = json.loads(l); r.pop("ts", None); print("LEDGER", r)
for l in (out / "events.jsonl").read_text().splitlines():
    e = json.loads(l)
    if e.get("type") != "message_end":
        continue
    m = e["message"]; c = m.get("content")
    who = f"{m.get('role')}/{m.get('model', '')}"
    if isinstance(c, list):
        for b in c:
            if b.get("type") == "text" and b["text"].strip():
                print(who, "TEXT", b["text"][:300].replace("\n", " | "))
            elif b.get("type") == "toolCall":
                print(who, "CALL", b["name"], json.dumps(b["arguments"])[:150])
    elif c:
        print(who, str(c)[:300].replace("\n", " | "))
print("FILES", sorted(p.name for p in (out / "work").iterdir()))
err = (out / "stderr.txt").read_text().strip()
if err:
    print("STDERR", err[-800:])
