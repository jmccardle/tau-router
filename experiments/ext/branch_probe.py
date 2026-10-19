"""Probe what a router/planner pair can rely on from ctx.spawn_branch.

``/probe [hooks]`` spawns two sub-agents concurrently. Branch A is asked to call the
``delegate`` tool, which spawns a nested sub-agent; branch B writes a file. Every
``message_end`` (with its cursor id and model) and every spawn's start/end time is
appended to ``branch_probe.log`` in the working directory, so the run answers:

1. do branch completions reach an extension's message_end, and with which cursor id?
2. do concurrent spawns overlap in time?
3. can a branch spawn a branch (recursion)?
4. with hooks=True, do this extension's hooks run inside branches?
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

LOG = Path("branch_probe.log")


def log(**row: Any) -> None:
    with LOG.open("a") as f:
        f.write(json.dumps({"t": round(time.time(), 3), **row}) + "\n")


def register(api: Any) -> None:
    def on_message_end(event: Any) -> None:
        message = getattr(event, "message", None)
        if isinstance(message, dict) and isinstance(message.get("usage"), dict):
            log(kind="message_end", cursor=getattr(event, "cursor_id", None), model=message.get("model"),
                tokens=message["usage"].get("total_tokens"))

    def on_tool_call(event: dict[str, Any], ctx: Any) -> None:
        log(kind="tool_call_hook", tool=event.get("tool_name"), cursor=getattr(ctx.cursor, "id", None))

    def anchor(ctx: Any, inside_tool: bool) -> str | None:
        """Where a sub-agent's context ends. Inside a tool call, the leaf is the assistant message
        holding that still-unanswered call, so branch from its parent instead."""
        leaf = ctx.cursor.leaf
        if not inside_tool:
            return leaf
        return next((e.get("parentId") for e in ctx.entries() if e.get("id") == leaf), None)

    async def spawn(ctx: Any, label: str, prompt: str, model: str, tools: list[str], hooks: bool,
                    inside_tool: bool = False) -> Any:
        log(kind="spawn_start", label=label, model=model, parent_cursor=getattr(ctx.cursor, "id", None))
        result = await ctx.spawn_branch(anchor(ctx, inside_tool), prompt, tools=tools, model=model, max_turns=6,
                                        label=label, hooks=hooks)
        log(kind="spawn_end", label=label, ok=result.ok, cursor=result.cursor_id, error=result.error)
        return result

    async def delegate(tool_call_id, params, signal, on_update, ctx):  # noqa: ANN001
        try:
            result = await spawn(ctx, "nested", params["prompt"], params.get("model", "ministral-3b"),
                                 ["write"], bool(params.get("hooks", True)), inside_tool=True)
        except Exception as exc:  # noqa: BLE001 - the probe's job is to record it
            log(kind="spawn_raised", label="nested", error=f"{type(exc).__name__}: {exc}")
            raise
        text = "ok" if result.ok else f"failed: {result.error}"
        return {"content": [{"type": "text", "text": f"nested sub-agent {text}"}]}

    async def probe(args: str, ctx: Any) -> str:
        hooks = args.strip() == "hooks"
        a = spawn(ctx, "A", "Call the delegate tool exactly once with prompt \"Use the write tool to write "
                  "the word nested into nested.txt\" and model \"ministral-3b\". Then reply done.",
                  "mistral-small", ["delegate", "write"], hooks)
        b = spawn(ctx, "B", "Use the write tool to write the word two into b.txt, then reply done.",
                  "ministral-3b", ["write"], hooks)
        results = await asyncio.gather(a, b)
        return "; ".join(f"{r.label}: ok={r.ok} err={r.error}" for r in results)

    api.on("message_end", on_message_end)
    api.on("tool_call", on_tool_call)
    api.register_tool({
        "name": "delegate",
        "description": "Spawn a sub-agent with its own model to do one small task.",
        "parameters": {"type": "object", "properties": {
            "prompt": {"type": "string"}, "model": {"type": "string"}, "hooks": {"type": "boolean"}},
            "required": ["prompt"]},
        "execute": delegate,
    })
    api.register_command("probe", {"description": "spawn branches and log what happens", "handler": probe})
