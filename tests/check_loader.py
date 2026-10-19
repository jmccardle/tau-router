"""Drive Tau's real extension loader on the installed router and planner, and find the router over pub/sub.

Not a pytest test: it needs the installed package and Tau's private loader, but no model and no network.
CI runs it outside the checkout, and it builds its own Tau home:

    python -I tests/check_loader.py
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from tau_agent_core.events import EventBus
from tau_agent_core.extension_types import ExtensionAPI
from tau_agent_core.extensions.registry import ExtensionRegistry
from tau_agent_core.extensions.runner import ExtensionHandlers
from tau_agent_core.sdk import _load_one_extension

from tau_router.cli import extension_paths

home = Path(tempfile.mkdtemp())
(home / ".tau").mkdir()
priced = {"input": 1.0, "output": 1.0, "cache_read": 0.1}
(home / ".tau" / "config.json").write_text(json.dumps({"models": {
    "big": {"backend": "anthropic", "model": "big-1", "cost": priced},
    "free": {"backend": "nvidia", "model": "free-1", "cost": {"input": 0.0, "output": 0.0, "cache_read": 0.0}},
}}))
os.environ["TAU_PORTABLE_BASE"] = str(home)

CONFIG = {
    "router": {"profiles": {"p": ["big", "free"]}, "profile": "p",
               "budgets": {"anthropic": {"cost": 1.0, "period": "day"}}},
    "planner": {},
}
registry = ExtensionRegistry()
bus = EventBus()
apis: dict[str, ExtensionAPI] = {}


def api_factory(label):
    api = ExtensionAPI(registry=registry, event_bus=bus, hook_handlers=ExtensionHandlers(path=label),
                       config=CONFIG[Path(label).stem])
    apis[Path(label).stem] = api
    return api


async def main() -> None:
    for path in extension_paths():
        await _load_one_extension(path, api_factory)
    tools = sorted(registry.get_active_tools())
    assert tools == ["budget_status", "delegate"], tools
    commands = sorted(registry.get_commands())
    for name in ("budget", "models", "profile", "tier"):
        assert any(c.endswith(name) for c in commands), (name, commands)
    payload: dict = {}
    await apis["planner"].emit("need_router", payload)
    router = payload.get("router")
    assert router is not None, "the planner's need_router reached no router"
    assert router.profile == "p" and router.currency == "$", (router.profile, router.currency)
    print(f"loaded {[p.name for p in extension_paths()]}; tools {tools}; commands {commands}")
    print("OK")


asyncio.run(main())
