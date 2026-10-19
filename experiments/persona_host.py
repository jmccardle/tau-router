"""Keep one Tau session working on a goal across governor-forced model switches.

Each round is one ``tau -p`` process on the same session (``--continue`` after the
first). When the governor aborted a round to switch models, the host resumes the
session with the governor's resume note; otherwise the goal is considered done
(or abandoned) by the agent and the host stops.

    python experiments/persona_host.py OUTDIR --goal "..." --model haiku \
        --ext 'ladder=["haiku","mistral-small"]' --ext 'budgets={...}'
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TAU = os.environ.get("TAU_BIN", "tau")  # the tau executable to run


RECOVERABLE = ("not valid JSON", "HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 529", "overloaded")


def recoverable(error: str) -> bool:
    """Errors a retry can plausibly fix: malformed tool calls and transient provider failures."""
    return any(k in error for k in RECOVERABLE)


def turn_error(events: Path, skip: int) -> str | None:
    """The error of the last failed agent_end this round wrote, if any."""
    found = None
    for line in events.read_text().splitlines()[skip:]:
        e = json.loads(line)
        if e.get("type") == "agent_end" and e.get("error"):
            found = str(e["error"])
    return found


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("out", type=Path)
    p.add_argument("--goal", required=True)
    p.add_argument("--model", required=True, help="first round's model (the governor may override)")
    p.add_argument("--ext", action="append", default=[], help="governor KEY=JSON, repeatable")
    p.add_argument("--max-rounds", type=int, default=6)
    p.add_argument("--error-resumes", type=int, default=3, help="resume after a recoverable turn error this many times")
    p.add_argument("--tau-home", type=Path, default=HERE / "home")
    p.add_argument("--keep-work", action="store_true", help="reuse OUT/work instead of starting empty")
    p.add_argument("--seed", type=Path, help="copy this directory's files into the empty work dir")
    p.add_argument("--score", help="shell command run in the work dir afterwards; its last line is the score")
    args = p.parse_args()

    out = args.out.resolve()
    work = out / "work"
    if not args.keep_work and out.exists():
        for f in ("events.jsonl", "stderr.txt", "ledger.jsonl", "rounds.jsonl"):
            (out / f).unlink(missing_ok=True)
        subprocess.run(["rm", "-rf", str(work)], check=True)
    work.mkdir(parents=True, exist_ok=True)
    if args.seed and not args.keep_work:
        subprocess.run(["cp", "-r", f"{args.seed.resolve()}/.", str(work)], check=True)
    ledger = out / "ledger.jsonl"
    env = {**os.environ, "HOME": str(args.tau_home)}
    exts = [f"governor.{e}" for e in args.ext] + [f"governor.ledger={json.dumps(str(ledger))}"]

    prompt = args.goal
    error_resumes = 0
    for rnd in range(args.max_rounds):
        seen = len(ledger.read_text().splitlines()) if ledger.exists() else 0
        events_seen = len((out / "events.jsonl").read_text().splitlines()) if (out / "events.jsonl").exists() else 0
        cmd = [str(TAU), "-p", "--mode", "json", "-ne", "-e", str(HERE / "ext" / "governor.py")]
        if rnd == 0:
            cmd += ["-m", args.model]
        else:
            cmd += ["--continue"]
        for e in exts:
            cmd += ["--ext-config", e]
        cmd.append(prompt)
        t0 = time.time()
        with (out / "events.jsonl").open("a") as ev, (out / "stderr.txt").open("a") as er:
            rc = subprocess.run(cmd, cwd=work, env=env, stdout=ev, stderr=er, timeout=1200).returncode
        new = [json.loads(line) for line in ledger.read_text().splitlines()[seen:]] if ledger.exists() else []
        switch = next((r for r in reversed(new) if r.get("kind") == "switch" and r.get("abort")), None)
        halted = any(r.get("kind") in ("halt", "refused") for r in new)
        error = turn_error(out / "events.jsonl", events_seen) if rc != 0 else None
        with (out / "rounds.jsonl").open("a") as f:
            f.write(json.dumps({"round": rnd, "rc": rc, "seconds": round(time.time() - t0, 1),
                                "prompt": prompt[:200], "switched_to": switch and switch["to"],
                                "halted": halted, "error": error and error[:300]}) + "\n")
        print(f"round {rnd}: rc={rc} switched_to={switch and switch['to']} halted={halted} "
              f"error={error and error[:80]!r}", flush=True)
        if halted:
            break
        if rc != 0:
            if error is None or not recoverable(error) or error_resumes >= args.error_resumes:
                break
            error_resumes += 1
            prompt = (f"[host] Your last step failed: {error.splitlines()[0][:300]} "
                      "Continue the task from where you are. If a tool call was rejected, retry it "
                      "with smaller arguments, for example one function per edit.")
            continue
        if switch is None:
            break
        prompt = switch["resume_note"]
    if args.score:
        res = subprocess.run(args.score, shell=True, cwd=work, capture_output=True, text=True, timeout=120)
        last = (res.stdout.strip().splitlines() or ["(no output)"])[-1]
        (out / "score.txt").write_text(res.stdout)
        print(f"score: {last}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
