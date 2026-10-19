"""``tau-router``: print what Tau needs to load the installed extensions.

Tau 0.13 loads extensions only from files: ``~/.tau/extensions`` or ``-e <path>``. Until it finds
them through the ``tau.extensions`` entry points (john/tau #35), ``tau $(tau-router ext-args)``
loads both from wherever pip put them. Nothing is copied into ``~/.tau``.
"""

from __future__ import annotations

import argparse
from importlib import resources
from pathlib import Path

EXTENSIONS = ("router", "planner")


def extension_paths() -> list[Path]:
    """The installed file of each extension."""
    package = resources.files("tau_router.ext")
    return [Path(str(package / f"{name}.py")) for name in EXTENSIONS]


def prompt_dir() -> Path:
    """The directory holding ``plan.md``, the ``/plan`` prompt template."""
    return Path(str(resources.files("tau_router") / "prompts"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tau-router", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ext-args", help="print '-e <path>' for each extension: tau $(tau-router ext-args)")
    sub.add_parser("prompt-dir", help="print the directory holding plan.md, the /plan template")
    args = parser.parse_args(argv)
    if args.command == "ext-args":
        print(" ".join(f"-e {p}" for p in extension_paths()))
    else:
        print(prompt_dir())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
