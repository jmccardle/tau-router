"""``tau-router``: print where the installed package keeps what Tau can't find by itself.

Tau finds both extensions through the ``tau.extensions`` entry points. It doesn't yet read a
prompt template an extension ships (john/tau #39), so ``/plan`` needs ``plan.md`` linked into a
Tau prompt directory; ``tau-router prompt-dir`` says where it is.
"""

from __future__ import annotations

import argparse
from importlib import resources
from pathlib import Path


def prompt_dir() -> Path:
    """The directory holding ``plan.md``, the ``/plan`` prompt template."""
    return Path(str(resources.files("tau_router") / "prompts"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tau-router", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prompt-dir", help="print the directory holding plan.md, the /plan template")
    parser.parse_args(argv)
    print(prompt_dir())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
