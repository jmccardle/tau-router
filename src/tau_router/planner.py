"""Planner: hand parts of a job to sub-agents, each with a model, a budget slice and a done-check.

Tau loads it as ``tau_router.ext.planner``. It needs the router extension loaded too: the planner
finds it over Tau's pub/sub (``ext:planner:need_router``) and opens each sub-agent's budget slice
there.

* ``/plan <goal>`` is the prompt template ``tau_router/prompts/plan.md``: it asks the current model
  to plan ``goal`` with ``delegate``. Tau 0.13 reads templates only from its prompt directories, and
  an extension can't add one yet (john/tau #39), so it's there only if you link it in.
* ``delegate`` runs one sub-agent and returns its outcome: did its check pass, what it spent,
  what is left of the planner's own budget, and the sub-agent's final words.
  - The sub-agent starts at its parent's *assignment* (the nearest user message or brief above the
    current step), so it sees the goal but not the parent's own work so far.
  - A failed check is retried once, one rung up the profile, while the budget allows.
  - With ``subplanner: true`` the sub-agent gets ``delegate`` too, and its slice is its budget.

Starting a child uses Tau's seeded ``spawn_branch``: the child's context is the parent's assignment,
a model-switch note, and a ``start_subagent`` call whose result is the brief.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from tau_agent_core.seed import seed_tool_call

DEFAULT_TOOLS = ["read", "write", "edit", "bash"]
START = "start_subagent"



def brief_text(task_id: str, brief: str, model: str, budget: str, check: str | None, sub: bool) -> str:
    lines = [f"[planner] You are a sub-agent running as {model}, assigned task {task_id!r} with a budget "
             f"of {budget}.", "", brief, ""]
    if check:
        lines.append(f"The task is done when this command exits 0: {check}")
        lines.append("Run it yourself before you finish.")
    if sub:
        lines.append("You may split this task further with the delegate tool; your budget is the total.")
    lines.append("When you finish, reply with a short summary of what you did and what, if anything, is left.")
    return "\n".join(lines)


def assignment(ctx: Any) -> str | None:
    """The entry a child branches from: the parent's own assignment.

    For the top-level planner that is the user message it is answering; for a sub-agent it is the
    ``start_subagent`` result its own brief arrived in. The child then sees the shared prefix (the
    real goal, cache-friendly) and none of the parent's work after it.
    """
    entries = {e.get("id"): e for e in ctx.entries()}
    node = entries.get(ctx.cursor.leaf)
    while node is not None:
        message = node.get("message") or {}
        role = message.get("role")
        if node.get("type") == "message" and (
                role == "user" or (role == "toolResult" and message.get("tool_name") == START)):
            return node["id"]
        node = entries.get(node.get("parentId"))
    return None


async def start_child(ctx: Any, at: str | None, brief: str, *, tools: list[str], model: str,
                      label: str, task_id: str, budget: float, shown: str) -> Any:
    """John's seeded branch: at the parent's assignment, a model-switch note, then a synthetic
    start_subagent call whose result is the brief; the child continues that agent turn."""
    note = {"customType": "router", "display": True,
            "content": f"[router] Model switch: you now run as {model}, a sub-agent with a {shown} budget."}
    seed = [note, *seed_tool_call(START, {"task_id": task_id, "model": model, "budget_cost": budget}, brief)]
    return await ctx.spawn_branch(at, seed=seed, tools=tools, model=model, max_turns=40, label=label, hooks=True)


async def run_check(check: str, cwd: str) -> tuple[bool, str]:
    proc = await asyncio.create_subprocess_shell(check, cwd=cwd, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    except TimeoutError:
        proc.kill()
        return False, "check timed out after 120s"
    return proc.returncode == 0, out.decode(errors="replace")[-600:]


def final_text(result: Any) -> str:
    for message in reversed(result.messages or []):
        if message.get("role") == "assistant":
            text = "".join(b.get("text", "") for b in message.get("content") or [] if b.get("type") == "text")
            if text.strip():
                return text.strip()[-800:]
    return result.error or "(no final text)"


def register(api: Any) -> None:
    labels_used: set[str] = set()

    async def find_router() -> Any:
        payload: dict[str, Any] = {}
        await api.emit("need_router", payload)
        if "router" not in payload:
            raise RuntimeError("planner: the router extension (tau_router.ext.router) is not loaded")
        return payload["router"]

    async def delegate(tool_call_id, params, signal, on_update, ctx):  # noqa: ANN001
        router = await find_router()
        names = [r.name for r in router.rungs]
        model, budget = params["model"], float(params["budget_cost"])
        if model not in names[router.tier:]:
            return error(f"model {model!r} is not within your tier: {names[router.tier:]}")
        parent = router.account_of(ctx)
        if parent is not None:
            left = router.accounts[parent]["cap"] - router.account_spent(parent)
        elif router.persona_cost is not None:
            left = router.persona_cost - router.spent(None, time.time())
        else:
            left = None
        if left is not None and budget > left:
            return error(f"budget {router.money(budget)} is more than the {router.money(left)} you have left")
        task_id = params["task_id"]
        label = f"{parent or 'root'}/{task_id}"
        while label in labels_used:
            label += "+"
        labels_used.add(label)
        sub = bool(params.get("subplanner"))
        tools = list(params.get("tools") or DEFAULT_TOOLS) + (["delegate", "budget_status"] if sub else [])
        check = params.get("check")
        at = assignment(ctx)
        attempts = []
        rung = names.index(model)
        while True:
            name = names[rung]
            attempt_label = label if not attempts else f"{label}#{len(attempts) + 1}"
            router.open_account(attempt_label, budget, parent=parent)
            shown = router.money(budget)
            result = await start_child(ctx, at, brief_text(task_id, params["brief"], name, shown, check, sub),
                                       tools=tools, model=name, label=attempt_label, task_id=task_id,
                                       budget=budget, shown=shown)
            passed, output = (await run_check(check, ctx.cwd)) if check else (result.ok, "")
            attempts.append({"model": name, "ok": result.ok, "check_passed": passed,
                             "spent": round(router.account_spent(attempt_label), 6),
                             "check_output": output[-300:], "final": final_text(result)})
            spent_total = sum(a["spent"] for a in attempts)
            can_escalate = rung - 1 >= router.tier and (left is None or spent_total + budget <= left)
            if passed or len(attempts) >= 2 or not params.get("escalate", True) or not can_escalate:
                break
            rung -= 1
        spent_total = sum(a["spent"] for a in attempts)
        report = {"task_id": task_id, "passed": attempts[-1]["check_passed"], "attempts": attempts,
                  "spent": round(spent_total, 6), "currency": router.currency,
                  "your_budget_left": None if left is None else round(left - spent_total, 6)}
        return {"content": [{"type": "text", "text": json.dumps(report, indent=1)}],
                "is_error": not report["passed"]}

    def error(text: str) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": text}], "is_error": True}

    api.register_tool({
        "name": "delegate",
        "description": ("Hand one part of the job to a sub-agent with its own model, budget slice and done-check. "
                        "Returns whether the check passed, what was spent, and your remaining budget."),
        "parameters": {"type": "object", "properties": {
            "task_id": {"type": "string", "description": "short unique name for this part"},
            "brief": {"type": "string", "description": "self-contained instructions; the sub-agent sees the "
                      "original goal but none of your work"},
            "model": {"type": "string", "description": "a model of your profile, at or below your tier"},
            "budget_cost": {"type": "number", "description": "this part's budget slice, in the currency "
                            "budget_status reports"},
            "check": {"type": "string", "description": "shell command that exits 0 when the part is done"},
            "tools": {"type": "array", "items": {"type": "string"}},
            "subplanner": {"type": "boolean", "description": "let the sub-agent delegate further"},
            "escalate": {"type": "boolean", "description": "retry once a rung up if the check fails (default true)"},
        }, "required": ["task_id", "brief", "model", "budget_cost"]},
        "execute": delegate,
    })
