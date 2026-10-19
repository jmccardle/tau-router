"""What Tau finds: the entry points, the files `tau-router ext-args` names, and the prompt."""

from __future__ import annotations

from importlib.metadata import entry_points

from tau_router.cli import extension_paths, main, prompt_dir


def test_entry_points_name_each_extension_module():
    ours = [ep for ep in entry_points(group="tau.extensions") if ep.dist and ep.dist.name == "ffwf-tau-router"]
    found = {ep.name: ep.value for ep in ours}
    # Tau names an extension by its module (john/tau #35), so these are the real modules, not tau_router.ext.
    assert found == {"router": "tau_router.router", "planner": "tau_router.planner"}
    for ep in ours:
        assert callable(ep.load().register)


def test_ext_args_names_files_tau_can_load(capsys):
    assert main(["ext-args"]) == 0
    assert capsys.readouterr().out.split() == [w for p in extension_paths() for w in ("-e", str(p))]
    assert [p.stem for p in extension_paths()] == ["router", "planner"]  # Tau names them by stem
    assert all(p.is_file() for p in extension_paths())


def test_the_plan_template_ships_with_the_package():
    assert "$ARGUMENTS" in (prompt_dir() / "plan.md").read_text()
