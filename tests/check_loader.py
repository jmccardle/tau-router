"""Drive the installed ``tau`` on the installed router and planner: discovery, authorization, config, pub/sub.

Not a pytest test: it needs the installed package and Tau's CLI, but no model and no network.
Each run builds its own Tau home, so nothing touches ~/.tau. CI runs it outside the checkout:

    python -I tests/check_loader.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tau_agent_core.testing import child_env

TAU = shutil.which("tau", path=str(Path(sys.executable).parent)) or sys.exit("tau is not installed beside python")
home = Path(tempfile.mkdtemp())
(home / ".tau").mkdir()
# Unreachable on purpose: a command that reached the model would fail loudly instead of passing.
model = {"backend": "anthropic", "api_key": "unused", "base_url": "http://127.0.0.1:9"}
priced = {"input": 1.0, "output": 1.0, "cache_read": 0.1}
(home / ".tau" / "config.json").write_text(json.dumps({
    "models": {"big": {**model, "model": "big-1", "cost": priced},
               "free": {**model, "model": "free-1", "cost": {"input": 0.0, "output": 0.0, "cache_read": 0.0}}},
    "default_model": "big",
    "extensions": {"tau_router.router": {"profiles": {"p": ["big", "free"]}, "profile": "p",
                                         "budgets": {"anthropic": {"cost": 1.0, "period": "day"}}},
                   "tau_router.planner": {}},
}))


def tau(*args: str) -> subprocess.CompletedProcess[str]:
    out = subprocess.run([TAU, *args], cwd=home, env=child_env(home), capture_output=True, text=True, timeout=120)
    print(f"$ tau {' '.join(args)}  -> {out.returncode}")
    return out


def ext_states() -> dict[str, str]:
    rows = [line.split() for line in tau("ext", "list").stdout.splitlines() if line.startswith("tau_router.")]
    return {row[0]: row[1] for row in rows}


ours = {"tau_router.router", "tau_router.planner"}
assert ext_states() == dict.fromkeys(ours, "unauthorized"), ext_states()
for name in sorted(ours):
    assert tau("ext", "authorize", name).returncode == 0
assert ext_states() == dict.fromkeys(ours, "authorized"), ext_states()

# /budget runs in the router, so no request is made. --verbose prints Tau's orphan-subscription notices
# (john/tau #44): the router's need_router subscription must match the planner's emitter.
run = tau("--verbose", "-p", "/budget")
assert run.returncode == 0, run.stderr
assert run.stdout.startswith("Routing on profile 'p', tier big; now on big [anthropic]."), run.stdout
assert "subscribes to" not in run.stderr and "failed to load" not in run.stderr, run.stderr

assert tau("ext", "disable", "tau_router.planner").returncode == 0
alone = tau("--verbose", "-p", "/budget")
assert "tau_router.router subscribes to ext:tau_router.planner:need_router" in alone.stderr, alone.stderr
print("OK")
