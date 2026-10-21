"""What Tau finds: the entry points, and the prompt."""

from __future__ import annotations

from importlib.metadata import entry_points

from tau_router.cli import main, prompt_dir


def test_entry_points_name_each_extension_module():
    ours = [ep for ep in entry_points(group="tau.extensions") if ep.dist and ep.dist.name == "ffwf-tau-router"]
    found = {ep.name: ep.value for ep in ours}
    # Tau names an extension by the module an entry point names (john/tau #35).
    assert found == {"router": "tau_router.router", "planner": "tau_router.planner"}
    for ep in ours:
        assert callable(ep.load().register)


def test_the_plan_template_ships_with_the_package(capsys):
    assert main(["prompt-dir"]) == 0
    assert capsys.readouterr().out.strip() == str(prompt_dir())
    assert "$ARGUMENTS" in (prompt_dir() / "plan.md").read_text()
