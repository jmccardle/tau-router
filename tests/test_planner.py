"""The planner's delegate tool against a fake spawn_branch: slices, checks and escalation."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from tests.conftest import FakeApi, FakeCtx, load_router


class PlannerCtx(FakeCtx):
    """A head that records each child it starts, and finishes it with ``reply``."""

    def __init__(self, model: str, reply: str = "done", **kw: Any) -> None:
        super().__init__(model, **kw)
        self.children: list[dict[str, Any]] = []
        self.reply = reply

    async def spawn_branch(self, at: Any, **kw: Any) -> SimpleNamespace:
        self.children.append(kw)
        text = {"role": "assistant", "content": [{"type": "text", "text": self.reply}]}
        return SimpleNamespace(ok=True, messages=[text], error=None)


def load_planner(tau_home, **router_overrides):
    from tau_router.ext import planner as ext

    router, router_api = load_router(tau_home, **router_overrides)
    api = FakeApi({})
    api.peers.append(router_api)
    ext.register(api)
    return router, api.tools["delegate"]["execute"]


async def delegate(execute, ctx, **params):
    out = await execute("t1", params, None, None, ctx)
    return out, json.loads(out["content"][0]["text"])


async def test_a_passing_part_runs_once_on_its_own_slice(tau_home):
    router, execute = load_planner(tau_home)
    ctx = PlannerCtx("big")
    out, report = await delegate(execute, ctx, task_id="a", brief="do a", model="mid", budget_cost=0.25,
                                 check="true")
    assert not out["is_error"] and report["passed"]
    (child,) = ctx.children
    assert child["model"] == "mid" and child["label"] == "root/a"
    assert router.accounts["root/a"]["cap"] == 0.25
    note, call, result = child["seed"]
    assert note["content"] == "[router] Model switch: you now run as mid, a sub-agent with a $0.2500 budget."
    assert "budget of $0.2500" in json.dumps(result)


async def test_a_failed_check_is_retried_once_a_rung_up(tau_home):
    _, execute = load_planner(tau_home)
    ctx = PlannerCtx("big")
    out, report = await delegate(execute, ctx, task_id="a", brief="do a", model="free", budget_cost=0.1,
                                 check="false")
    assert out["is_error"] and not report["passed"]
    assert [c["model"] for c in ctx.children] == ["free", "mid"]
    assert [c["label"] for c in ctx.children] == ["root/a", "root/a#2"]


async def test_a_slice_larger_than_what_is_left_is_refused(tau_home):
    _, execute = load_planner(tau_home, persona_cost=0.5)
    ctx = PlannerCtx("big")
    out = await execute("t1", {"task_id": "a", "brief": "b", "model": "mid", "budget_cost": 0.75}, None, None, ctx)
    assert out["is_error"]
    assert out["content"][0]["text"] == "budget $0.7500 is more than the $0.5000 you have left"
    assert ctx.children == []


async def test_a_model_above_the_tier_is_refused(tau_home):
    _, execute = load_planner(tau_home, tier="mid")
    ctx = PlannerCtx("mid")
    out = await execute("t1", {"task_id": "a", "brief": "b", "model": "big", "budget_cost": 0.1}, None, None, ctx)
    assert out["is_error"] and "not within your tier" in out["content"][0]["text"]


async def test_without_the_router_delegate_fails_loudly(tau_home):
    from tau_router.ext import planner as ext

    api = FakeApi({})
    ext.register(api)
    with pytest.raises(RuntimeError, match="router extension"):
        await api.tools["delegate"]["execute"](
            "t1", {"task_id": "a", "brief": "b", "model": "mid", "budget_cost": 0.1}, None, None, PlannerCtx("big"))
