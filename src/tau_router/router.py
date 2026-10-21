"""The router extension: choose the model for each request from a profile, within your budgets.

Tau loads it as ``tau_router.router``. Its config lives under ``extensions."tau_router.router"``:

    profiles      {name: [model config names, best first]}
    profile       the active profile name
    tier          the highest rung this session may use (a model name in the profile; default: the first)
    budgets       {provider: {"cost": 0.05, "period": "day"|"month"|"once", "anchor_day": 8, "since": 0}}
    persona_cost  optional cap on all spending together
    reserve_cost  a priced rung needs this much headroom to be chosen (default 0.002)
    currency      the symbol amounts are shown with (default "$"); amounts are in the currency your
                  model prices are written in, and nothing is converted
    mode          "auto" (the router picks) or "agent" (the model may pick with select_model)
    hold_seconds  how long a refused model is held when the refusal names no Retry-After (default 60)
    ledger        JSONL path (default <tau home>/ext-state/tau-router.jsonl)

A switch takes effect on the next request of the same loop, and is recorded so --continue
resumes on it. A rung Tau can't use (its config entry doesn't build, or its provider refused the
key) is skipped for the rest of the process, and says why in /budget and as a session warning.
"""

from __future__ import annotations

import json
import time
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tau_agent_core import ModelUnavailableError
from tau_agent_core.tau_home import resolve_tau_home
from tau_agent_core.usage import price_usage

USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
# Renamed in 0.1 so amounts aren't tied to one currency. Old names are refused, not aliased.
RENAMED = {"persona_usd": "persona_cost", "reserve_usd": "reserve_cost"}


@dataclass(frozen=True)
class Rung:
    name: str
    model_id: str
    provider: str
    cost: dict[str, float] | None

    @property
    def free(self) -> bool:
        return self.cost is not None and not any(self.cost.values())


def check_config(cfg: dict[str, Any]) -> None:
    """Refuse config written for 0.0.x key names, saying what each became, and budgets the router can't keep."""
    old = [f"{k} -> {v}" for k, v in RENAMED.items() if k in cfg]
    old += [f"budgets.{p}.usd -> budgets.{p}.cost" for p, b in (cfg.get("budgets") or {}).items() if "usd" in b]
    if old:
        raise ValueError(f"router: config uses renamed keys: {'; '.join(old)}")
    uncapped = [p for p, b in (cfg.get("budgets") or {}).items() if "cost" not in b]
    if uncapped:
        raise ValueError(f"router: budgets for {uncapped} have no 'cost' cap")
    for p, b in (cfg.get("budgets") or {}).items():
        anchor = b.get("anchor_day", 1)
        if type(anchor) is not int or not 1 <= anchor <= 31:
            raise ValueError(f"router: budgets.{p}.anchor_day is {anchor!r}; it must be a day of the month, 1-31")


def period_start(budget: dict[str, Any], now: float) -> float:
    period = budget.get("period", "day")
    d = datetime.fromtimestamp(now, UTC)
    if period == "once":
        return float(budget.get("since", 0))
    if period == "day":
        return datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()
    anchor = budget.get("anchor_day", 1)
    if d.day >= min(anchor, monthrange(d.year, d.month)[1]):
        y, m = d.year, d.month
    else:
        y, m = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
    # A month too short for the anchor resets on its last day, as billing cycles do.
    return datetime(y, m, min(anchor, monthrange(y, m)[1]), tzinfo=UTC).timestamp()


class Router:
    def __init__(self, api: Any) -> None:
        cfg = dict(api.config or {})
        # Tau gives an extension no model catalog yet (john/tau #24), so read its config file.
        tau_config = json.loads((resolve_tau_home() / "config.json").read_text())
        if not cfg:
            old = " tau-router 0.1 read extensions.router, which is still there; rename it." \
                if "router" in (tau_config.get("extensions") or {}) else ""
            raise ValueError(f'router: no config under extensions."tau_router.router" in config.json.{old}')
        check_config(cfg)
        models = tau_config.get("models", {})
        # Every config model is priced and attributed, not only the profile's: you may pick any with /model.
        self.models = {n: Rung(n, m["model"], m.get("backend", "?"), m.get("cost")) for n, m in models.items()}
        self.by_id: dict[str, Rung] = {}
        for rung in self.models.values():
            self.by_id.setdefault(rung.model_id, rung)
        self.profiles: dict[str, list[str]] = cfg.get("profiles") or {}
        for pname, names in self.profiles.items():
            missing = [n for n in names if n not in self.models]
            if missing:
                raise ValueError(f"router: profile {pname!r} names {missing}, which are not in config models")
        self.use_profile(cfg.get("profile"), cfg.get("tier"))
        self.pinned: Rung | None = None
        self.last_set_id: str | None = None
        self.budgets: dict[str, dict[str, Any]] = cfg.get("budgets", {})
        self.persona_cost: float | None = cfg.get("persona_cost")
        self.reserve = float(cfg.get("reserve_cost", 0.002))
        self.currency = str(cfg.get("currency", "$"))
        self.mode = cfg.get("mode", "auto")
        self.hold_seconds = float(cfg.get("hold_seconds", 60))
        self.ledger = Path(cfg.get("ledger") or resolve_tau_home() / "ext-state" / "tau-router.jsonl")
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.api = api
        # Per cursor: parallel planner branches each have their own pending switch and last model.
        self.wanted: dict[str | None, tuple[Rung, str]] = {}
        self.exhausted: dict[str | None, str] = {}
        # The model each cursor's next request goes to: what the router last set, else what last answered.
        self.last_model: dict[str | None, str | None] = {}
        self.accounts: dict[str, dict[str, Any]] = {}
        # Rung name -> why Tau can't use it. Not in the ledger: a fixed config or key works after a restart.
        self.unusable: dict[str, str] = {}
        self.refused = False  # the head's last turn was refused: every rung within the tier is blocked
        self.session_id: str | None = None
        self.warnings: dict[str, tuple[str, str]] = {}

    def money(self, amount: float, digits: int = 4) -> str:
        return f"{self.currency}{amount:.{digits}f}"

    def use_profile(self, name: str | None, tier: str | None = None) -> None:
        if name not in self.profiles:
            raise ValueError(f"router: profile {name!r} is not one of {sorted(self.profiles)}")
        self.rungs = [self.models[n] for n in self.profiles[name]]
        names = [r.name for r in self.rungs]
        tier = tier or names[0]
        if tier not in names:
            raise ValueError(f"router: tier {tier!r} is not a rung of profile {name!r}: {names}")
        self.profile, self.tier = name, names.index(tier)

    # -- ledger -------------------------------------------------------------------------------

    def rows(self) -> list[dict[str, Any]]:
        if not self.ledger.exists():
            return []
        return [json.loads(line) for line in self.ledger.read_text().splitlines() if line.strip()]

    def append(self, **row: Any) -> None:
        with self.ledger.open("a") as f:
            f.write(json.dumps({"ts": time.time(), **row}) + "\n")

    def spent(self, provider: str | None, now: float) -> float:
        since = 0.0 if provider is None else period_start(self.budgets.get(provider, {}), now)
        return sum(r.get("cost") or 0.0 for r in self.rows()
                   if r["kind"] == "usage" and r["ts"] >= since and provider in (None, r["provider"]))

    def held(self, rung: Rung, now: float) -> str | None:
        for r in self.rows():
            if r["kind"] == "hold" and r["model"] == rung.model_id and r["until"] > now:
                return r["why"]
        return None

    # -- choosing -----------------------------------------------------------------------------

    def headroom(self, rung: Rung, now: float) -> float | None:
        limits: list[float] = []
        if rung.provider in self.budgets:
            limits.append(float(self.budgets[rung.provider]["cost"]) - self.spent(rung.provider, now))
        if self.persona_cost is not None:
            limits.append(float(self.persona_cost) - self.spent(None, now))
        return min(limits) if limits else None

    def blocked(self, rung: Rung, now: float) -> str | None:
        """Why this rung can't take the next request, or None."""
        if rung.name in self.unusable:
            return f"unusable: {self.unusable[rung.name]}"
        hold = self.held(rung, now)
        if hold:
            return f"held: {hold}"
        if rung.cost is None and (rung.provider in self.budgets or self.persona_cost is not None):
            return "unpriced under a budget"
        h = self.headroom(rung, now)
        if h is not None and not rung.free and h < self.reserve:
            return f"{self.money(h)} headroom"
        return None

    def best(self, now: float, start: int | None = None) -> Rung | None:
        for r in self.rungs[self.tier if start is None else max(start, self.tier):]:
            if self.blocked(r, now) is None:
                return r
        return None

    def status(self, current_id: str | None) -> dict[str, Any]:
        now = time.time()
        return {
            "running_on": self.by_id[current_id].name if current_id in self.by_id else current_id,
            "profile": self.profile, "tier": self.rungs[self.tier].name,
            "currency": self.currency,
            "persona": None if self.persona_cost is None else
            {"cap": self.persona_cost, "spent": round(self.spent(None, now), 6)},
            "providers": {p: {"cap": b["cost"], "period": b.get("period", "day"),
                              "spent": round(self.spent(p, now), 6)} for p, b in self.budgets.items()},
            "rungs": [{"name": r.name, "provider": r.provider, "price_per_M_in_out":
                       None if r.cost is None else [r.cost.get("input"), r.cost.get("output")],
                       "within_tier": i >= self.tier, "blocked": self.blocked(r, now)}
                      for i, r in enumerate(self.rungs)],
        }

    # -- reports (/budget, /models) -------------------------------------------------------------

    def routing_line(self, live_id: str | None) -> str:
        cur = self.by_id.get(live_id or "")
        on = f"{cur.name} [{cur.provider}]" if cur else str(live_id)
        if self.pinned is not None:
            return f"Pinned to {self.pinned.name} (you picked it); /profile {self.profile} resumes routing."
        return f"Routing on profile {self.profile!r}, tier {self.rungs[self.tier].name}; now on {on}."

    def budget_report(self, live_id: str | None) -> str:
        now = time.time()
        rows = [r for r in self.rows() if r["kind"] == "usage"]
        day0 = period_start({"period": "day"}, now)
        providers = sorted({r["provider"] for r in rows} | set(self.budgets))
        out = [self.routing_line(live_id), "",
               f"{'provider':12} {'period spend':>13} {'cap':>9} {'period':>7} {'calls today':>12} {'unpriced':>9}"]
        for prov in providers:
            b = self.budgets.get(prov)
            since = period_start(b, now) if b else day0
            mine = [r for r in rows if r["provider"] == prov and r["ts"] >= since]
            today = [r for r in rows if r["provider"] == prov and r["ts"] >= day0]
            cost = sum(r.get("cost") or 0.0 for r in mine)
            unpriced = sum(1 for r in mine if r.get("cost") is None)
            cap = self.money(b["cost"], 2) if b else "-"
            period = b.get("period", "day") if b else "day"
            out.append(f"{prov:12} {self.money(cost):>13} {cap:>9} {period:>7} {len(today):>12} {unpriced or '':>9}")
        if self.persona_cost is not None:
            out.append(f"{'(all)':12} {self.money(self.spent(None, now)):>13} {self.money(self.persona_cost, 2):>9}")
        out += ["", "Rungs:"]
        for i, r in enumerate(self.rungs):
            mark = ">" if r.model_id == live_id else " "
            state = "above tier" if i < self.tier else (self.blocked(r, now) or "ok")
            out.append(f" {mark} {r.name:16} [{r.provider}] {state}")
        if self.accounts:
            out += ["", "Planner slices this session:"]
            for label, acct in self.accounts.items():
                out.append(f"   {label:40} {self.money(self.account_spent(label))} of {self.money(acct['cap'])}")
        out += ["", f"Ledger: {self.ledger}"]
        return "\n".join(out)

    def show_status(self, ctx: Any) -> None:
        """The TUI's status strip: the model now routed to and its provider's spend against its cap."""
        if not getattr(ctx.ui, "interactive", False) or self.account_of(ctx) is not None:
            return
        live = ctx.get_model().get("id")
        rung = self.by_id.get(live or "")
        now = time.time()
        where = f"{rung.name} [{rung.provider}]" if rung else str(live)
        mode = "pinned" if self.pinned is not None else self.profile
        cap = self.budgets.get(rung.provider) if rung else None
        spend = ""
        if rung and cap:
            spent = self.money(self.spent(rung.provider, now), 3)
            spend = f" {spent}/{self.money(cap['cost'], 2)} {cap.get('period', 'day')}"
        ctx.ui.set_status("router", f"router: {where} · {mode}{spend}")

    def models_report(self, live_id: str | None) -> str:
        in_profiles: dict[str, list[str]] = {}
        for pname, names in self.profiles.items():
            for i, n in enumerate(names):
                in_profiles.setdefault(n, []).append(f"{pname}#{i + 1}")
        by_provider: dict[str, list[Rung]] = {}
        for r in self.models.values():
            by_provider.setdefault(r.provider, []).append(r)
        out = [self.routing_line(live_id), "Pick any with /model <name>; that pins it.", ""]
        for prov in sorted(by_provider):
            cap = self.budgets.get(prov)
            budget = f"  (budget {self.money(cap['cost'], 2)}/{cap.get('period', 'day')})" if cap else ""
            out.append(f"{prov}{budget}")
            for r in by_provider[prov]:
                if r.cost is None:
                    price = "unpriced"
                elif r.free:
                    price = "free"
                else:
                    c = self.currency
                    price = f"{c}{r.cost.get('input', 0):g}/{c}{r.cost.get('output', 0):g} per M"
                mark = ">" if r.model_id == live_id else " "
                where = ", ".join(in_profiles.get(r.name, []))
                out.append(f" {mark} {r.name:18} {r.model_id:38} {price:22} {where}")
        return "\n".join(out)

    # -- hooks --------------------------------------------------------------------------------

    def on_message_end(self, event: Any) -> None:
        message = getattr(event, "message", None)
        if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
            return
        usage, model_id = message["usage"], message.get("model")
        cursor = getattr(event, "cursor_id", None)
        self.last_model[cursor] = model_id
        rung = self.by_id.get(model_id or "")
        cost = price_usage(rung.cost if rung else None, usage)
        headers = getattr(event, "response_headers", None) or {}
        quota = {k: v for k, v in headers.items() if "ratelimit" in k and "remaining" in k}
        self.append(kind="usage", cursor=cursor, model=model_id,
                    provider=rung.provider if rung else str(message.get("provider") or "?"),
                    **{k: int(usage.get(k) or 0) for k in USAGE_KEYS}, cost=cost,
                    stop=message.get("stop_reason"), quota=quota or None)
        # A pin belongs to the head session; on_turn_end drops a step-down there, not in a branch.
        if rung is not None and rung in self.rungs and cursor not in self.wanted:
            now = time.time()
            reason = self.blocked(rung, now)
            if reason is not None:
                nxt = self.best(now, self.rungs.index(rung) + 1)
                if nxt is not None:
                    self.wanted[cursor] = (nxt, f"{rung.name} {reason}")
                else:
                    self.exhausted[cursor] = f"{rung.name} {reason}, and no rung below it is available"

    def on_refusal(self, event: Any) -> None:
        detail = getattr(event, "error_detail", None)
        model_id = self.last_model.get(getattr(event, "cursor_id", None))
        if detail is None or model_id is None:
            return
        if detail.status in (401, 403):
            # Not retried, so it reaches agent_end only. Every turn on this rung would be refused the same way.
            rung = self.by_id.get(model_id)
            if rung is not None:
                why = {False: "no API key", True: "API key refused"}.get(detail.key_sent, "refused")
                self.mark_unusable(rung, f"{why} (HTTP {detail.status})")
            return
        if detail.status not in (429, 503, 529):
            return
        wait = detail.retry_after if detail.retry_after is not None else self.hold_seconds
        self.append(kind="hold", model=model_id, until=time.time() + wait,
                    why=f"HTTP {detail.status}, {wait:.0f}s ({'Retry-After' if detail.retry_after else 'default'})")

    def mark_unusable(self, rung: Rung, why: str) -> None:
        self.unusable[rung.name] = " ".join(why.split())  # a warning is one line
        self.append(kind="unusable", model=rung.name, why=self.unusable[rung.name])
        self.refresh_warnings()

    def try_set(self, ctx: Any, rung: Rung) -> bool:
        """Switch ``ctx`` to ``rung``; a rung Tau refuses is marked unusable instead (#65)."""
        try:
            ctx.set_model(rung.name)
        except KeyError as exc:
            self.mark_unusable(rung, f"not a configured model ({exc.args[0] if exc.args else rung.name})")
            return False
        except ModelUnavailableError as exc:
            self.mark_unusable(rung, str(exc))
            return False
        return True

    def route(self, ctx: Any, choose: Any, why: str, current: Rung | None) -> Rung | None:
        """Move ``ctx`` to the rung ``choose()`` names, asking again past each rung Tau refuses.

        ``choose`` reads ``blocked``, which counts a refused rung from then on, so the loop ends.
        Returns the rung the next request goes to, or None when ``choose`` has none.
        """
        while (target := choose()) is not None:
            if current is not None and current.name == target.name:
                break
            if self.try_set(ctx, target):
                self.append(kind="switch", frm=current and current.name, to=target.name, why=why,
                            cursor=ctx.cursor.id)
                break
        else:
            return None
        if self.account_of(ctx) is None:
            self.last_set_id = target.model_id
        self.last_model[ctx.cursor.id] = target.model_id
        return target

    def new_session(self, ctx: Any) -> None:
        """Forget what belonged to the previous conversation; /new, fork and resume fire no hook."""
        sid = ctx.session_id
        if sid == self.session_id:
            return
        if self.session_id is not None:
            self.pinned, self.last_set_id, self.refused = None, None, False
            self.wanted.pop(ctx.cursor.id, None)
            self.exhausted.pop(ctx.cursor.id, None)
        self.session_id = sid

    def refresh_warnings(self) -> None:
        """Show what keeps the router from routing normally as Tau session warnings (#60); clear what ended."""
        now = time.time()
        want: dict[str, tuple[str, str]] = {}
        for prov, b in self.budgets.items():
            if float(b["cost"]) - self.spent(prov, now) < self.reserve:
                want[f"budget:{prov}"] = (f"{prov} budget ({self.money(b['cost'], 2)}/{b.get('period', 'day')}) "
                                          "is spent; its priced rungs are skipped until it resets", "warning")
        if self.persona_cost is not None and float(self.persona_cost) - self.spent(None, now) < self.reserve:
            want["budget:all"] = (f"the overall budget ({self.money(self.persona_cost, 2)}) is spent; "
                                  "only free rungs are used", "warning")
        for name, why in self.unusable.items():
            want[f"model:{name}"] = (f"{name} is skipped: {why}", "warning")
        if self.pinned is not None:
            want["pin"] = (f"pinned to {self.pinned.name}; routing is paused until /profile {self.profile}",
                           "warning")
        if self.refused:
            want["refused"] = ("every rung within the tier is blocked, so turns are refused; /budget shows why",
                               "error")
        for key, (message, severity) in want.items():
            if self.warnings.get(key) != (message, severity):
                self.api.set_warning(key, message, severity)
        for key in self.warnings.keys() - want.keys():
            self.api.clear_warning(key)
        self.warnings = want

    def on_input(self, event: dict[str, Any], ctx: Any) -> dict[str, Any] | None:
        now = time.time()
        live = ctx.get_model()
        current = self.by_id.get(live.get("id"))
        if self.account_of(ctx) is not None and current is not None:
            # A branch with a planner account keeps the planner's model unless it is blocked.
            # (Seeded branches skip input hooks; this covers branches started with a prompt.)
            rest = self.rungs[self.rungs.index(current):] if current in self.rungs else self.rungs[self.tier:]

            def keep() -> Rung | None:
                return current if self.blocked(current, now) is None else \
                    next((r for r in rest if self.blocked(r, now) is None), None)

            return None if self.route(ctx, keep, "branch start: blocked", current) else {"handled": True}
        self.new_session(ctx)

        # A model you chose yourself (/model, or -m outside the profile) is pinned: the router stops
        # choosing until /profile or /tier, or until that model is blocked.
        picked_by_hand = (live.get("id") != self.last_set_id) if self.last_set_id is not None \
            else (current is not None and current not in self.rungs)
        if picked_by_hand and (self.pinned is None or self.pinned.model_id != live.get("id")):
            self.pinned = current or Rung(str(live.get("id")), str(live.get("id")), str(live.get("provider")), None)
            self.append(kind="pin", model=self.pinned.name)
            note = "" if self.pinned.cost is not None else " It has no price in config, so its spending is not counted."
            ctx.ui.notify(f"router: you picked {self.pinned.name}; automatic routing is paused. "
                          f"/profile {self.profile} resumes it.{note}", "info")
        if self.pinned is not None:
            why = self.blocked(self.pinned, now)
            if why == "unpriced under a budget":
                # Your explicit choice wins; its spending just can't be counted. /budget says so.
                why = None
            if why is None:
                self.last_set_id = self.pinned.model_id
                self.last_model[ctx.cursor.id] = self.pinned.model_id
                return None
            ctx.ui.notify(f"router: {self.pinned.name} is blocked ({why}); back on profile {self.profile}.",
                          "warning")
            self.append(kind="unpin", model=self.pinned.name, why=why)
            self.pinned = None

        def choose() -> Rung | None:
            target = self.best(now)
            if target is not None and self.mode == "agent" and current in self.rungs \
                    and self.rungs.index(current) >= self.tier:
                # The agent's own choice stands while it is within tier and unblocked; when blocked,
                # step down from it rather than jump to the top.
                target = current if self.blocked(current, now) is None else \
                    (self.best(now, self.rungs.index(current)) or target)
            return target

        self.refused = self.route(ctx, choose, "turn start", current) is None
        if self.refused:
            ctx.ui.notify("router: every rung within the tier is blocked; turn refused. /budget shows why.",
                          "warning")
            self.append(kind="refused", why={r.name: self.blocked(r, now) for r in self.rungs})
            return {"handled": True}
        return None

    def switch_to(self, ctx: Any, why: str) -> Rung | None:
        """Route the head from the best rung now, as /profile and /tier do; None when every rung is blocked."""
        now = time.time()
        return self.route(ctx, lambda: self.best(now), why, self.by_id.get(ctx.get_model().get("id")))

    # -- accounts: budget slices for branch cursors ------------------------------------------

    def open_account(self, label: str, cap: float, parent: str | None = None) -> None:
        """A budget slice for the branch whose cursor carries ``label``; spending under it, and
        under any branch it spawns, counts against ``cap``."""
        self.accounts[label] = {"cap": float(cap), "parent": parent, "cursors": set()}
        self.append(kind="account", label=label, cap=cap, parent=parent)

    def account_spent(self, label: str) -> float:
        labels = {label} | {lb for lb in self.accounts if self._descends(lb, label)}
        cursors = set().union(*(self.accounts[lb]["cursors"] for lb in labels))
        return sum(r.get("cost") or 0.0 for r in self.rows() if r["kind"] == "usage" and r.get("cursor") in cursors)

    def _descends(self, label: str, ancestor: str) -> bool:
        parent = self.accounts.get(label, {}).get("parent")
        while parent is not None:
            if parent == ancestor:
                return True
            parent = self.accounts.get(parent, {}).get("parent")
        return False

    def account_of(self, ctx: Any) -> str | None:
        label = getattr(ctx.cursor, "label", None)
        if label in self.accounts:
            self.accounts[label]["cursors"].add(ctx.cursor.id)
            return label
        return None

    def on_turn_end(self, event: dict[str, Any], ctx: Any) -> dict[str, Any] | None:
        label = self.account_of(ctx)
        if label is not None:
            spent, cap = self.account_spent(label), self.accounts[label]["cap"]
            if spent >= cap:
                used = f"{self.money(spent)} of {self.money(cap)}"
                self.append(kind="halt", account=label, why=f"{used} slice spent")
                ctx.abort()
                return {"message": {"customType": "router", "display": True, "content":
                                    f"[router] Your budget slice is spent ({used}); stopping."}}
        cursor = ctx.cursor.id
        exhausted = self.exhausted.pop(cursor, None)
        wanted = self.wanted.pop(cursor, None)
        if label is None and self.pinned is not None:
            return None  # your pick stands; on_input unpins it once it is blocked
        if exhausted:
            self.append(kind="halt", why=exhausted, cursor=cursor)
            ctx.abort()
            return {"message": {"customType": "router", "display": True,
                                "content": f"[router] Stopping: {exhausted}."}}
        if wanted is None:
            return None
        want, why = wanted
        frm = self.by_id.get(self.last_model.get(cursor) or "")
        now = time.time()
        # The wanted rung, else (if Tau refuses it) the best one below it. route() keeps the head's
        # last_set_id; a switch inside a planner branch is not the head session's model.
        start = self.rungs.index(want)
        rung = self.route(ctx, lambda: want if self.blocked(want, now) is None else self.best(now, start + 1),
                          why, frm)
        if rung is None:
            stop = f"{want.name} is {self.blocked(want, now)}, and no rung below it is available"
            self.append(kind="halt", why=stop, cursor=cursor)
            ctx.abort()
            return {"message": {"customType": "router", "display": True, "content": f"[router] Stopping: {stop}."}}
        if rung is not want:
            why = f"{why}; {want.name} is {self.blocked(want, now)}"
        return {"message": {"customType": "router", "display": True, "content":
                            f"[router] From the next step you run as {rung.name} ({why}). "
                            "Your work so far is above; continue from the next unfinished step."}}


def register(api: Any) -> None:
    router = Router(api)

    async def budget_status(tool_call_id, params, signal, on_update, ctx):  # noqa: ANN001
        return {"content": [{"type": "text", "text": json.dumps(router.status(ctx.get_model().get("id")), indent=1)}]}

    async def select_model(tool_call_id, params, signal, on_update, ctx):  # noqa: ANN001
        rung = next((r for r in router.rungs if r.name == params["name"]), None)
        if rung is None or router.rungs.index(rung) < router.tier:
            return {"content": [{"type": "text", "text": f"{params['name']} is not available within your tier"}],
                    "is_error": True}
        why = router.blocked(rung, time.time())
        if why:
            return {"content": [{"type": "text", "text": f"{rung.name} is blocked: {why}"}], "is_error": True}
        router.wanted[ctx.cursor.id] = (rung, f"the agent chose it: {params.get('reason', '')}")
        return {"content": [{"type": "text", "text": f"Switching to {rung.name} from your next step."}]}

    def on_lookup(payload: Any) -> None:
        # Other extensions find this router through Tau's pub/sub: they emit ext:<them>:need_router
        # with a dict, and the router puts itself in it.
        if isinstance(payload, dict):
            payload["router"] = router

    async def budget_cmd(args: str, ctx: Any) -> str:
        return router.budget_report(ctx.get_model().get("id"))

    async def models_cmd(args: str, ctx: Any) -> str:
        return router.models_report(ctx.get_model().get("id"))

    async def profile_cmd(args: str, ctx: Any) -> str:
        name = args.strip()
        if not name:
            lines = [router.routing_line(ctx.get_model().get("id")), ""]
            for pname, names in router.profiles.items():
                lines.append(f"{'*' if pname == router.profile else ' '} {pname}: {' > '.join(names)}")
            return "\n".join(lines + ["", "/profile <name> switches (and resumes routing if you pinned a model)."])
        if name not in router.profiles:
            return f"No profile {name!r}. Profiles: {', '.join(router.profiles)}"
        router.use_profile(name)
        router.pinned = None
        target = router.switch_to(ctx, f"/profile {name}")
        router.refresh_warnings()
        if target is None:
            return f"Profile {name}: every rung is blocked right now. /budget shows why."
        return f"Profile {name}; routing resumed on {target.name} [{target.provider}] from the next request."

    async def tier_cmd(args: str, ctx: Any) -> str:
        names = [r.name for r in router.rungs]
        tier = args.strip()
        if not tier:
            return f"Tier: {names[router.tier]} (profile {router.profile}: {' > '.join(names)}). /tier <rung> sets it."
        if tier not in names:
            return f"{tier!r} is not a rung of {router.profile}: {' > '.join(names)}"
        router.use_profile(router.profile, tier)
        router.pinned = None
        target = router.switch_to(ctx, f"/tier {tier}")
        router.refresh_warnings()
        if target is None:
            return f"Tier {tier}: every rung at or below it is blocked. /budget shows why."
        return f"Tier {tier}; now on {target.name} [{target.provider}] from the next request."

    for name, handler, desc in (
            ("budget", budget_cmd, "Spending per provider against its budget, the rungs, and planner slices"),
            ("models", models_cmd, "Every configured model by provider, with prices and profiles"),
            ("profile", profile_cmd, "Show or switch the routing profile; resumes routing after a /model pick"),
            ("tier", tier_cmd, "Show or set the highest rung the router may use")):
        api.register_command(name, {"description": desc, "handler": handler})

    api.on("ext:tau_router.planner:need_router", on_lookup)
    api.on("message_end", router.on_message_end)
    api.on("provider_retry", router.on_refusal)
    api.on("agent_end", router.on_refusal)

    def on_input(event: dict[str, Any], ctx: Any) -> dict[str, Any] | None:
        result = router.on_input(event, ctx)
        router.refresh_warnings()
        router.show_status(ctx)
        return result

    def on_turn_end(event: dict[str, Any], ctx: Any) -> dict[str, Any] | None:
        result = router.on_turn_end(event, ctx)
        router.refresh_warnings()
        router.show_status(ctx)
        return result

    def on_session_start(event: dict[str, Any], ctx: Any) -> None:
        # Tau 0.14 opens the TUI's session at mount (john/tau #42), so paint the strip before the first input.
        router.refresh_warnings()
        router.show_status(ctx)

    api.on("input", on_input)
    api.on("turn_end", on_turn_end)
    api.on("session_start", on_session_start)
    api.register_tool({
        "name": "budget_status",
        "description": "Your own spending: budgets, what is spent, which model you run on and which you can use.",
        "parameters": {"type": "object", "properties": {}},
        "execute": budget_status,
    })
    if router.mode == "agent":
        api.register_tool({
            "name": "select_model",
            "description": ("Switch the model that runs you, from your next step. Pick the cheapest model that "
                            "will do the next part well; bigger models cost more of your budget."),
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string", "enum": [r.name for r in router.rungs[router.tier:]]},
                "reason": {"type": "string"}}, "required": ["name"]},
            "execute": select_model,
        })
