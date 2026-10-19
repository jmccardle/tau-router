"""Spend governor: a Tau extension that prices every completion per provider and
moves the session down a model ladder when budgets run out.

Exploratory prototype. Load with ``tau -e experiments/ext/governor.py``; its config
lives under ``extensions.governor`` in ~/.tau/config.json (or ``--ext-config
governor.KEY=JSON``):

    ladder        model config names, best first: ["haiku", "mistral-small", ...]
    budgets       {provider: {"usd": 0.05, "period": "day"|"month"|"once", "anchor_day": 8}}
    persona_usd   optional cap on the whole agent's spend, every provider together
    reserve_usd   a rung needs this much budget left to be chosen (default 0.002)
    mode          "auto": the governor picks the best affordable rung each prompt;
                  "agent": the model picks with the select_model tool, the governor
                  only vetoes and enforces
    handoff       on a forced switch, tell the next model what happened (default true)
    ledger        JSONL path (default ~/.tau/ext-state/governor.jsonl)

Prices and providers come from the ``models`` block of the same config.json, so a
model is priced exactly as Tau's own ``cost`` block says, cache writes included.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BUCKETS = (("input_tokens", "input"), ("output_tokens", "output"),
           ("cache_read_tokens", "cache_read"), ("cache_write_tokens", "cache_write"))


@dataclass(frozen=True)
class Rung:
    name: str
    model_id: str
    provider: str
    cost: dict[str, float] | None


def _period_start(budget: dict[str, Any], now: float) -> float:
    period = budget.get("period", "day")
    d = datetime.fromtimestamp(now, UTC)
    if period == "once":
        return float(budget.get("since", 0))
    if period == "day":
        return datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()
    anchor = int(budget.get("anchor_day", 1))
    y, m = (d.year, d.month) if d.day >= anchor else ((d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1))
    return datetime(y, m, anchor, tzinfo=UTC).timestamp()


def price(usage: dict[str, Any], cost: dict[str, float] | None) -> float | None:
    """USD for one completion; None when the model has no price (unknown, not free)."""
    if cost is None:
        return None
    return sum(float(usage.get(k) or 0) * float(cost.get(c, 0.0)) / 1e6 for k, c in BUCKETS)


class Governor:
    def __init__(self, api: Any) -> None:
        cfg = dict(api.config or {})
        tau_cfg = json.loads((Path.home() / ".tau" / "config.json").read_text())
        models = tau_cfg.get("models", {})
        self.rungs: list[Rung] = []
        for name in cfg.get("ladder") or []:
            if name not in models:
                raise ValueError(f"governor: ladder model {name!r} is not in ~/.tau/config.json models")
            m = models[name]
            self.rungs.append(Rung(name, m["model"], m.get("backend", "?"), m.get("cost")))
        if not self.rungs:
            raise ValueError("governor: 'ladder' must name at least one model")
        self.by_id = {r.model_id: r for r in self.rungs}
        self.budgets: dict[str, dict[str, Any]] = cfg.get("budgets", {})
        self.persona_usd: float | None = cfg.get("persona_usd")
        self.reserve = float(cfg.get("reserve_usd", 0.002))
        self.mode = cfg.get("mode", "auto")
        self.handoff = bool(cfg.get("handoff", True))
        self.ledger = Path(cfg.get("ledger") or Path.home() / ".tau" / "ext-state" / "governor.jsonl")
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.api = api
        self.pending: tuple[Rung, str] | None = None
        self.started = time.time()

    # -- ledger ---------------------------------------------------------------

    def _rows(self) -> list[dict[str, Any]]:
        if not self.ledger.exists():
            return []
        return [json.loads(line) for line in self.ledger.read_text().splitlines() if line.strip()]

    def _append(self, row: dict[str, Any]) -> None:
        with self.ledger.open("a") as f:
            f.write(json.dumps(row) + "\n")

    def spent(self, provider: str | None, now: float) -> float:
        """USD this provider's budget period has seen (all providers when None, since persona start)."""
        if provider is None:
            since = 0.0
        else:
            since = _period_start(self.budgets.get(provider, {}), now)
        return sum(r.get("usd") or 0.0 for r in self._rows()
                   if r.get("kind") == "usage" and r["ts"] >= since and (provider is None or r["provider"] == provider))

    def headroom(self, rung: Rung, now: float) -> float | None:
        """USD left for this rung: the tighter of its provider budget and the persona cap. None = unlimited."""
        limits: list[float] = []
        b = self.budgets.get(rung.provider)
        if b is not None:
            limits.append(float(b["usd"]) - self.spent(rung.provider, now))
        if self.persona_usd is not None:
            limits.append(float(self.persona_usd) - self.spent(None, now))
        return min(limits) if limits else None

    def affordable(self, rung: Rung, now: float) -> bool:
        if rung.cost is None and rung.provider in self.budgets:
            return False  # metered against a budget but unpriced: refuse rather than guess
        h = self.headroom(rung, now)
        if h is None:
            return True
        free = rung.cost is not None and not any(rung.cost.values())
        return free or h >= self.reserve

    def best_affordable(self, now: float, at_or_below: int = 0) -> Rung | None:
        for r in self.rungs[at_or_below:]:
            if self.affordable(r, now):
                return r
        return None

    def status(self, current_id: str | None) -> dict[str, Any]:
        now = time.time()
        return {
            "current_model": self.by_id[current_id].name if current_id in self.by_id else current_id,
            "persona": None if self.persona_usd is None else {
                "cap_usd": self.persona_usd, "spent_usd": round(self.spent(None, now), 6)},
            "providers": {p: {"cap_usd": b["usd"], "period": b.get("period", "day"),
                              "spent_usd": round(self.spent(p, now), 6)} for p, b in self.budgets.items()},
            "ladder": [{"name": r.name, "provider": r.provider, "usd_per_M_in_out":
                        None if r.cost is None else [r.cost.get("input"), r.cost.get("output")],
                        "affordable": self.affordable(r, now)} for r in self.rungs],
        }

    # -- hooks ----------------------------------------------------------------

    def on_message_end(self, event: Any) -> None:
        message = getattr(event, "message", None)
        if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
            return
        usage, model_id = message["usage"], message.get("model")
        rung = self.by_id.get(model_id)
        provider = rung.provider if rung else str(message.get("provider") or "?")
        usd = price(usage, rung.cost if rung else None)
        self._append({"ts": time.time(), "kind": "usage", "model": model_id, "provider": provider,
                      **{c: int(usage.get(k) or 0) for k, c in BUCKETS}, "usd": usd,
                      "stop": message.get("stop_reason")})
        if rung is None:
            return
        now = time.time()
        if not self.affordable(rung, now) and self.pending is None:
            nxt = self.best_affordable(now, self.rungs.index(rung) + 1)
            if nxt is not None:
                self.pending = (nxt, f"budget: {rung.provider} has ${self.headroom(rung, now):.4f} left")
            else:
                self.pending = None
                self._exhausted = True

    def on_input(self, event: dict[str, Any], ctx: Any) -> dict[str, Any] | None:
        now = time.time()
        current = self.by_id.get(ctx.get_model().get("id"))
        best = self.best_affordable(now)
        if best is None:
            ctx.ui.notify("governor: every rung is out of budget; turn refused", "warning")
            self._append({"ts": now, "kind": "refused", "prompt_chars": len(event.get("prompt") or "")})
            return {"handled": True}
        target = best
        if self.mode == "agent":
            # ctx.set_model is process-local and --continue resumes the session's recorded model,
            # so the agent's last choice is re-applied from the ledger on every prompt.
            chosen = self.chosen()
            if chosen is not None and self.affordable(chosen, now):
                target = chosen
        if current is None or current.name != target.name:
            ctx.set_model(target.name)
            self._append({"ts": now, "kind": "switch", "from": current and current.name, "to": target.name,
                          "why": "turn start"})
        return None

    def chosen(self) -> Rung | None:
        """The rung of the last abort-switch in the ledger: what the agent (or budget) last chose."""
        for row in reversed(self._rows()):
            if row.get("kind") == "switch" and row.get("abort"):
                return next((r for r in self.rungs if r.name == row["to"]), None)
        return None

    def on_turn_end(self, event: dict[str, Any], ctx: Any) -> dict[str, Any] | None:
        exhausted = getattr(self, "_exhausted", False)
        if self.pending is None and not exhausted:
            return None
        if exhausted:
            self._exhausted = False
            self._append({"ts": time.time(), "kind": "halt", "why": "no affordable rung"})
            ctx.abort()
            return {"message": {"customType": "governor", "display": True,
                                "content": "Budget exhausted on every model; stopping."}}
        rung, why = self.pending
        self.pending = None
        prev = ctx.get_model().get("id")
        ctx.set_model(rung.name)
        note = "Continue the task."
        if self.handoff:
            note = (f"[governor] You are now running as {rung.name} because {why}. The conversation "
                    "above is your own work so far, done by a different model. Re-read the original goal, "
                    "check what is already done, and continue from the next unfinished step. Do not "
                    "start over and do not stop early.")
        # A followUp queued here never runs: Tau reuses the aborted signal for followUp
        # re-entry (agent_session.py:2875 resets it per submission only). The host resumes instead.
        self._append({"ts": time.time(), "kind": "switch", "from": prev, "to": rung.name, "why": why,
                      "abort": True, "resume_note": note})
        ctx.abort()
        return None


def register(api: Any) -> None:
    gov = Governor(api)

    async def budget_status(tool_call_id, params, signal, on_update, ctx):  # noqa: ANN001
        return {"content": [{"type": "text", "text": json.dumps(gov.status(ctx.get_model().get("id")), indent=1)}]}

    async def select_model(tool_call_id, params, signal, on_update, ctx):  # noqa: ANN001
        name, reason = params["name"], params.get("reason", "")
        rung = next((r for r in gov.rungs if r.name == name), None)
        if rung is None:
            return {"content": [{"type": "text", "text": f"unknown model {name!r}"}], "is_error": True}
        if not gov.affordable(rung, time.time()):
            return {"content": [{"type": "text", "text": f"{name} is out of budget"}], "is_error": True}
        gov.pending = (rung, f"the agent chose it: {reason}")
        return {"content": [{"type": "text", "text": f"Switching to {name} after this step."}]}

    api.on("message_end", gov.on_message_end)
    api.on("input", gov.on_input)
    api.on("turn_end", gov.on_turn_end)
    api.register_tool({
        "name": "budget_status",
        "description": "Your own spending: per-provider budgets, what is spent, and which models you can afford.",
        "parameters": {"type": "object", "properties": {}},
        "execute": budget_status,
    })
    if gov.mode == "agent":
        api.register_tool({
            "name": "select_model",
            "description": ("Switch the model that runs you, effective after this step. Pick the cheapest "
                            "model that can do the next part well; bigger models cost more of your budget."),
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string", "enum": [r.name for r in gov.rungs]},
                "reason": {"type": "string"}}, "required": ["name"]},
            "execute": select_model,
        })
