"""A fake Tau for the extensions: the api they register on, the ctx their hooks get, and events.

No model is called. A test plays Tau's part: it fires ``input``, ``message_end`` and ``turn_end``
in the order a turn does, with the usage a provider would have reported.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tau_agent_core import ModelUnavailableError

PRICED = {"input": 1.0, "output": 1.0, "cache_read": 0.1}  # 1 per M, so 1M tokens cost 1.0
FREE = {"input": 0.0, "output": 0.0, "cache_read": 0.0}

MODELS = {
    "big": {"backend": "anthropic", "model": "big-1", "cost": PRICED},
    "mid": {"backend": "mistral", "model": "mid-1", "cost": PRICED},
    "free": {"backend": "nvidia", "model": "free-1", "cost": FREE},
    "unpriced": {"backend": "mistral", "model": "unpriced-1"},
}

ROUTER_CONFIG: dict[str, Any] = {
    "profiles": {"p": ["big", "mid", "free"], "free-only": ["free"]},
    "profile": "p",
    "budgets": {"anthropic": {"cost": 1.0, "period": "day"}, "mistral": {"cost": 1.0, "period": "day"}},
    "reserve_cost": 0.01,
}


class FakeApi:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.handlers: dict[str, list[Any]] = {}
        self.commands: dict[str, dict[str, Any]] = {}
        self.tools: dict[str, dict[str, Any]] = {}
        self.peers: list[FakeApi] = []  # the other extensions, for emit
        self.warnings: dict[str, tuple[str, str]] = {}
        self.warning_calls = 0

    def on(self, event: str, handler: Any) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def register_command(self, name: str, command: dict[str, Any]) -> None:
        self.commands[name] = command

    def register_tool(self, tool: dict[str, Any]) -> None:
        self.tools[tool["name"]] = tool

    async def emit(self, topic: str, payload: Any) -> None:
        # Tau publishes api.emit("t") from extension tau_router.planner as ext:tau_router.planner:t.
        for peer in [self, *self.peers]:
            for handler in peer.handlers.get(f"ext:tau_router.planner:{topic}", []):
                handler(payload)

    def set_warning(self, key: str, message: str, severity: str = "warning") -> None:
        assert "\n" not in message and severity in ("warning", "error"), (message, severity)
        self.warnings[key] = (message, severity)
        self.warning_calls += 1

    def clear_warning(self, key: str) -> None:
        self.warnings.pop(key, None)

    def fire(self, event: str, *args: Any) -> list[Any]:
        return [h(*args) for h in self.handlers.get(event, [])]


@dataclass
class FakeUi:
    interactive: bool = True
    notes: list[tuple[str, str]] = field(default_factory=list)
    status: dict[str, str] = field(default_factory=dict)

    def notify(self, text: str, level: str = "info") -> None:
        self.notes.append((text, level))

    def set_status(self, key: str, text: str) -> None:
        self.status[key] = text


class FakeCtx:
    """One cursor of a session: the head (label None) or a planner branch (label set)."""

    def __init__(self, model: str, cursor_id: str = "head", label: str | None = None,
                 ui: FakeUi | None = None, unavailable: dict[str, str] | None = None) -> None:
        self.model = model
        self.session_id = "s1"
        self.unavailable = unavailable or {}  # config name -> why Tau's set_model refuses it
        self.cursor = SimpleNamespace(id=cursor_id, label=label, leaf=None)
        self.ui = ui or FakeUi()
        self.aborted = False
        self.cwd = "."

    def get_model(self) -> dict[str, Any]:
        return {"id": MODELS[self.model]["model"], "provider": MODELS[self.model]["backend"]}

    def set_model(self, name: str) -> None:
        # As Tau's ctx.set_model: KeyError for a name not in config, ModelUnavailableError for one that won't build.
        if name not in MODELS:
            raise KeyError(name)
        if name in self.unavailable:
            raise ModelUnavailableError(self.unavailable[name])
        self.model = name

    def abort(self) -> None:
        self.aborted = True

    def entries(self) -> list[dict[str, Any]]:
        return []


def usage_event(ctx: FakeCtx, tokens: int = 0, model: str | None = None) -> SimpleNamespace:
    """A message_end for one call on ``ctx``'s model that read ``tokens`` input tokens."""
    message = {"role": "assistant", "model": MODELS[model or ctx.model]["model"], "stop_reason": "end_turn",
               "usage": {"input_tokens": tokens, "output_tokens": 0}}
    return SimpleNamespace(message=message, cursor_id=ctx.cursor.id, response_headers={})


def refusal_event(ctx: FakeCtx, status: int = 429, retry_after: float | None = 30,
                  key_sent: bool | None = None) -> SimpleNamespace:
    detail = SimpleNamespace(status=status, retry_after=retry_after, key_sent=key_sent)
    return SimpleNamespace(error_detail=detail, cursor_id=ctx.cursor.id)


@pytest.fixture
def tau_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A HOME whose ~/.tau/config.json holds MODELS; the router reads it for prices."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TAU_PORTABLE_BASE", raising=False)
    home = tmp_path / ".tau"
    home.mkdir()
    (home / "config.json").write_text(json.dumps({"models": MODELS}))
    return home


def load_router(tau_home: Path, **overrides: Any) -> tuple[Any, FakeApi]:
    """Register the router extension on a fake api; returns (router, api)."""
    from tau_router import router as ext

    api = FakeApi({**json.loads(json.dumps(ROUTER_CONFIG)), **overrides})
    ext.register(api)
    (lookup,) = api.handlers["ext:tau_router.planner:need_router"]
    payload: dict[str, Any] = {}
    lookup(payload)
    return payload["router"], api
