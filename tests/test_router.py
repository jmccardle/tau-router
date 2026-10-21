"""The router extension against a scripted turn: routing, step-downs, pins, holds and slices."""

from __future__ import annotations

import json
import time

import pytest

from tests.conftest import FakeCtx, FakeUi, load_router, refusal_event, usage_event

M = 1_000_000  # tokens that cost 1.0 on a PRICED model


def rows(router, kind):
    return [r for r in router.rows() if r["kind"] == kind]


def test_turn_start_routes_to_the_top_rung(tau_home):
    router, api = load_router(tau_home)
    ctx = FakeCtx("mid")
    assert api.fire("input", {}, ctx) == [None]
    assert ctx.model == "big"
    assert rows(router, "switch")[-1]["to"] == "big"


def test_a_spent_budget_steps_down_from_the_next_request(tau_home):
    router, api = load_router(tau_home)
    ctx = FakeCtx("big")
    api.fire("input", {}, ctx)
    api.fire("message_end", usage_event(ctx, M))  # anthropic's 1.0 is spent
    (out,) = api.fire("turn_end", {}, ctx)
    assert ctx.model == "mid"
    assert out["message"]["content"].startswith("[router] From the next step you run as mid")
    assert rows(router, "usage")[-1]["cost"] == pytest.approx(1.0)


def test_nothing_left_below_halts_the_turn(tau_home):
    router, api = load_router(tau_home, profiles={"p": ["big", "mid"]})
    ctx = FakeCtx("big")
    api.fire("message_end", usage_event(ctx, M, model="mid"))  # mistral spent elsewhere
    api.fire("message_end", usage_event(ctx, M))
    (out,) = api.fire("turn_end", {}, ctx)
    assert ctx.aborted
    assert "no rung below it is available" in out["message"]["content"]


def test_every_rung_blocked_refuses_the_turn(tau_home):
    router, api = load_router(tau_home, profiles={"p": ["big", "mid"]})
    ctx = FakeCtx("big")
    api.fire("message_end", usage_event(ctx, M, model="big"))
    api.fire("message_end", usage_event(ctx, M, model="mid"))
    assert api.fire("input", {}, ctx) == [{"handled": True}]
    assert rows(router, "refused")


def test_step_downs_are_per_cursor(tau_home):
    router, api = load_router(tau_home)
    a, b = FakeCtx("big", "a", "root/a"), FakeCtx("big", "b", "root/b")
    router.open_account("root/a", 5.0)
    router.open_account("root/b", 5.0)
    api.fire("message_end", usage_event(a, M))  # a's call spends anthropic's cap
    assert api.fire("turn_end", {}, b) == [None]  # b's switch is computed on b's own next call
    assert b.model == "big"
    api.fire("turn_end", {}, a)
    assert a.model == "mid"


def test_your_model_pick_is_pinned_until_it_is_blocked(tau_home):
    router, api = load_router(tau_home)
    ctx = FakeCtx("big")
    api.fire("input", {}, ctx)
    ctx.set_model("mid")  # /model mid
    api.fire("input", {}, ctx)
    assert ctx.model == "mid" and router.pinned.name == "mid"
    assert "automatic routing is paused" in ctx.ui.notes[-1][0]
    api.fire("message_end", usage_event(ctx, M))
    assert api.fire("turn_end", {}, ctx) == [None]  # a pin is not stepped down mid-turn
    api.fire("input", {}, ctx)
    assert router.pinned is None and ctx.model == "big"
    assert rows(router, "unpin")[-1]["model"] == "mid"


def test_a_head_pin_does_not_stop_a_branch_stepping_down(tau_home):
    router, api = load_router(tau_home)
    head = FakeCtx("big")
    api.fire("input", {}, head)
    router.pinned = router.models["big"]
    branch = FakeCtx("big", "c1", "root/x")
    router.open_account("root/x", 5.0)
    api.fire("message_end", usage_event(branch, M))
    api.fire("turn_end", {}, branch)
    assert branch.model == "mid"


def test_a_429_holds_the_model_that_was_refused(tau_home):
    router, api = load_router(tau_home)
    ctx = FakeCtx("big")
    api.fire("message_end", usage_event(ctx, 0))
    api.fire("provider_retry", refusal_event(ctx, 429, retry_after=30))
    assert router.blocked(router.models["big"], time.time()).startswith("held: HTTP 429, 30s")
    api.fire("input", {}, ctx)
    assert ctx.model == "mid"


def test_a_400_is_not_a_hold(tau_home):
    router, api = load_router(tau_home)
    ctx = FakeCtx("big")
    api.fire("message_end", usage_event(ctx, 0))
    api.fire("agent_end", refusal_event(ctx, 400, retry_after=None))
    assert not rows(router, "hold")


def test_a_rung_tau_cannot_build_is_skipped_not_run_over_budget(tau_home):
    """Tau #65: set_model raises for an entry that doesn't build. Uncaught, the turn ran on the old rung."""
    router, api = load_router(tau_home)
    ctx = FakeCtx("free", unavailable={"big": "anthropic: no such backend version\nsee config"})
    assert api.fire("input", {}, ctx) == [None]
    assert ctx.model == "mid"
    why = "unusable: anthropic: no such backend version see config"
    assert router.blocked(router.models["big"], time.time()) == why
    assert "[anthropic] " + why in router.budget_report("mid-1")
    assert api.warnings["model:big"] == ("big is skipped: anthropic: no such backend version see config", "warning")


def test_a_rung_missing_from_tau_config_is_skipped(tau_home):
    router, api = load_router(tau_home)
    ctx = FakeCtx("free")
    big = router.models["big"]
    router.models["ghost"] = big.__class__("ghost", "ghost-1", "anthropic", big.cost)  # in a profile, not in Tau
    router.rungs.insert(0, router.models["ghost"])
    api.fire("input", {}, ctx)
    assert ctx.model == "big"
    assert router.unusable == {"ghost": "not a configured model (ghost)"}


def test_a_wanted_step_down_that_tau_refuses_goes_one_further(tau_home):
    router, api = load_router(tau_home)
    ctx = FakeCtx("big", unavailable={"mid": "broken"})
    api.fire("input", {}, ctx)
    api.fire("message_end", usage_event(ctx, M))  # anthropic's 1.0 is spent; mid is wanted
    (out,) = api.fire("turn_end", {}, ctx)
    assert ctx.model == "free"
    assert "you run as free" in out["message"]["content"] and "mid is unusable: broken" in out["message"]["content"]


def test_every_rung_refused_by_tau_refuses_the_turn_with_an_error_warning(tau_home):
    router, api = load_router(tau_home)
    ctx = FakeCtx("free", unavailable={"big": "x", "mid": "y"})
    api.fire("message_end", usage_event(ctx, 0))
    api.fire("provider_retry", refusal_event(ctx, 429, retry_after=30))  # free is held
    assert api.fire("input", {}, ctx) == [{"handled": True}]
    assert ctx.model == "free"
    assert api.warnings["refused"][1] == "error"


@pytest.mark.parametrize(("key_sent", "why"), [
    (False, "no API key (HTTP 401)"), (True, "API key refused (HTTP 401)"), (None, "refused (HTTP 401)")])
def test_a_401_blocks_the_rung_the_request_went_to(tau_home, key_sent, why):
    router, api = load_router(tau_home)
    ctx = FakeCtx("mid")
    api.fire("message_end", usage_event(ctx, 0))  # mid answered last; the router now sends to big
    api.fire("input", {}, ctx)
    api.fire("agent_end", refusal_event(ctx, 401, retry_after=None, key_sent=key_sent))
    assert router.unusable == {"big": why}
    assert api.warnings["model:big"] == (f"big is skipped: {why}", "warning")
    api.fire("input", {}, ctx)
    assert ctx.model == "mid"


def test_spent_budgets_and_pins_are_warnings_until_they_end(tau_home):
    router, api = load_router(tau_home)
    ctx = FakeCtx("big")
    api.fire("input", {}, ctx)
    api.fire("message_end", usage_event(ctx, M))
    api.fire("turn_end", {}, ctx)
    assert api.warnings["budget:anthropic"][0].startswith("anthropic budget ($1.00/day) is spent")
    ctx.set_model("free")  # /model free
    api.fire("input", {}, ctx)
    assert "pin" in api.warnings
    calls = api.warning_calls
    api.fire("input", {}, ctx)
    assert api.warning_calls == calls  # an unchanged warning is not set again
    import asyncio

    asyncio.run(api.commands["profile"]["handler"]("p", ctx))
    assert "pin" not in api.warnings and ctx.model == "mid"


def test_a_new_conversation_drops_the_pin(tau_home):
    router, api = load_router(tau_home)
    ctx = FakeCtx("big")
    api.fire("input", {}, ctx)
    ctx.set_model("mid")
    api.fire("input", {}, ctx)
    assert router.pinned.name == "mid"
    ctx.session_id = "s2"  # /new: Tau fires no hook, but the id changes
    api.fire("input", {}, ctx)
    assert router.pinned is None and ctx.model == "big"
    assert "pin" not in api.warnings


def test_session_start_paints_the_status_strip(tau_home):
    _, api = load_router(tau_home)
    ctx = FakeCtx("big")
    api.fire("session_start", {"type": "session_start", "reason": "startup"}, ctx)
    assert ctx.ui.status["router"] == "router: big [anthropic] · p $0.000/$1.00 day"


def test_a_spent_slice_halts_its_branch(tau_home):
    router, api = load_router(tau_home)
    router.open_account("root/a", 0.5)
    branch = FakeCtx("mid", "c1", "root/a")
    api.fire("message_end", usage_event(branch, 600_000))
    (out,) = api.fire("turn_end", {}, branch)
    assert branch.aborted
    assert out["message"]["content"] == "[router] Your budget slice is spent ($0.6000 of $0.5000); stopping."


def test_a_child_slice_counts_against_its_parent(tau_home):
    router, api = load_router(tau_home)
    router.open_account("root/a", 1.0)
    router.open_account("root/a/b", 0.4, parent="root/a")
    child = FakeCtx("mid", "c2", "root/a/b")
    api.fire("input", {}, child)  # the cursor joins its account
    api.fire("message_end", usage_event(child, 300_000))
    assert router.account_spent("root/a") == pytest.approx(0.3)


def test_an_unpriced_model_is_refused_under_a_budget(tau_home):
    router, _ = load_router(tau_home, profiles={"p": ["unpriced", "free"]})
    assert router.blocked(router.models["unpriced"], 0) == "unpriced under a budget"
    assert router.best(0).name == "free"


@pytest.mark.parametrize(("overrides", "message"), [
    ({"persona_usd": 1.0}, "persona_usd -> persona_cost"),
    ({"reserve_usd": 0.1}, "reserve_usd -> reserve_cost"),
    ({"budgets": {"mistral": {"usd": 1.0}}}, "budgets.mistral.usd -> budgets.mistral.cost"),
])
def test_renamed_keys_are_refused(tau_home, overrides, message):
    with pytest.raises(ValueError, match=message.replace(".", r"\.")):
        load_router(tau_home, **overrides)


def test_a_config_left_under_the_0_1_key_is_named(tau_home):
    from tau_router import router as ext
    from tests.conftest import MODELS, ROUTER_CONFIG, FakeApi

    with pytest.raises(ValueError, match=r'no config under extensions\."tau_router\.router" in config\.json\.$'):
        ext.register(FakeApi({}))
    (tau_home / "config.json").write_text(json.dumps({"models": MODELS, "extensions": {"router": ROUTER_CONFIG}}))
    with pytest.raises(ValueError, match="0.1 read extensions.router, which is still there; rename it"):
        ext.register(FakeApi({}))


def test_a_budget_without_a_cap_is_refused(tau_home):
    with pytest.raises(ValueError, match="no 'cost' cap"):
        load_router(tau_home, budgets={"mistral": {"period": "day"}})


@pytest.mark.parametrize("anchor", [0, 32, "8", 8.0, True])
def test_an_anchor_day_that_is_not_a_day_of_the_month_is_refused(tau_home, anchor):
    with pytest.raises(ValueError, match=r"budgets\.mistral\.anchor_day is .*1-31"):
        load_router(tau_home, budgets={"mistral": {"cost": 1.0, "period": "month", "anchor_day": anchor}})


def test_the_status_strip_uses_the_currency_symbol(tau_home):
    router, api = load_router(tau_home, currency="€")
    ctx = FakeCtx("big")
    api.fire("input", {}, ctx)
    assert ctx.ui.status["router"] == "router: big [anthropic] · p €0.000/€1.00 day"
    assert "€" in router.budget_report("big-1")


def test_no_status_strip_without_an_interactive_head(tau_home):
    _, api = load_router(tau_home)
    ctx = FakeCtx("big", ui=FakeUi(interactive=False))
    api.fire("input", {}, ctx)
    assert ctx.ui.status == {}


async def test_budget_status_tool_reports_cost_and_currency(tau_home):
    _, api = load_router(tau_home)
    out = await api.tools["budget_status"]["execute"]("t1", {}, None, None, FakeCtx("big"))
    status = json.loads(out["content"][0]["text"])
    assert status["currency"] == "$"
    assert status["providers"]["anthropic"] == {"cap": 1.0, "period": "day", "spent": 0.0}


def test_a_monthly_budget_starts_on_its_anchor_day():
    from datetime import UTC, datetime

    from tau_router.router import period_start

    def ts(y, m, d):
        return datetime(y, m, d, 12, tzinfo=UTC).timestamp()

    mistral = {"cost": 5.0, "period": "month", "anchor_day": 1}  # a promo that resets on the 1st
    assert period_start(mistral, ts(2026, 10, 18)) == datetime(2026, 10, 1, tzinfo=UTC).timestamp()
    assert period_start(mistral, ts(2026, 1, 1)) == datetime(2026, 1, 1, tzinfo=UTC).timestamp()
    anthropic = {"cost": 3.0, "period": "month", "anchor_day": 8}
    assert period_start(anthropic, ts(2026, 10, 7)) == datetime(2026, 9, 8, tzinfo=UTC).timestamp()
    assert period_start(anthropic, ts(2026, 1, 7)) == datetime(2025, 12, 8, tzinfo=UTC).timestamp()


def test_an_anchor_past_the_end_of_a_short_month_resets_on_its_last_day():
    from datetime import UTC, datetime

    from tau_router.router import period_start

    def day(y, m, d, h=0):
        return datetime(y, m, d, h, tzinfo=UTC).timestamp()

    b31 = {"cost": 1.0, "period": "month", "anchor_day": 31}
    assert period_start(b31, day(2026, 2, 28, 12)) == day(2026, 2, 28)  # February has no 31st
    assert period_start(b31, day(2026, 3, 15, 12)) == day(2026, 2, 28)
    assert period_start(b31, day(2026, 3, 31, 12)) == day(2026, 3, 31)
    assert period_start(b31, day(2026, 4, 30, 12)) == day(2026, 4, 30)
    assert period_start({"cost": 1.0, "period": "month", "anchor_day": 29}, day(2028, 2, 29, 12)) == day(2028, 2, 29)
