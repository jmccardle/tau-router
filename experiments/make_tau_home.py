"""Build a sandbox HOME whose ~/.tau/config.json holds models from every provider in the .env.

Tau finds its config through ``Path.home()``, so ``HOME=experiments/home tau ...``
runs against this file and never touches the real ~/.tau. Keys are copied from
the given .env into the sandbox (gitignored), never printed.

    python experiments/make_tau_home.py --env PATH/TO/.env
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cache_probe import KEY_ENV, key_for, read_env
from tau_router.cli import prompt_dir

HERE = Path(__file__).resolve().parent

# name -> (provider, backend, model id, base_url or None, per-M prices or None if unknown, context window)
# Unpriced models are listed for /model; the router refuses them under a budget rather than guess.
# Windows are what each provider's model API reported on 2026-10-16; the Cerebras models and nemotron-super
# report none, so theirs are unverified.
MODELS: dict[str, tuple[str, str, str, str | None, dict[str, float] | None, int]] = {
    # Haiku 5.5 prices: platform.claude.com/docs/en/about-claude/pricing, read 2026-10-18. Above a 100K-token
    # prompt it bills $0.50/$2.50 per M; Tau prices one tier, so long prompts undercount.
    # The key is the model's API id, which Tau configs commonly use as its name.
    "claude-haiku-5-5": ("anthropic", "anthropic", "claude-haiku-5-5", None,
              {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125}, 1_000_000),
    "mistral-small": ("mistral", "mistral", "mistral-small-2603", "https://api.mistral.ai/v1",
                      {"input": 0.15, "output": 0.60, "cache_read": 0.015}, 262_144),
    "ministral-3b": ("mistral", "mistral", "ministral-3b-2512", "https://api.mistral.ai/v1",
                     {"input": 0.04, "output": 0.04, "cache_read": 0.004}, 131_072),
    # Cerebras Developer Tier prices, 2026-10-18. Cerebras lists no cache discount, so a cache read
    # is priced as input.
    "qwen-27b": ("cerebras", "cerebras", "qwen-3.8-27b", "https://api.cerebras.ai/v1",
                 {"input": 0.99, "output": 1.49, "cache_read": 0.99}, 128_000),
    "gpt-oss-120b": ("cerebras", "cerebras", "gpt-oss-120b", "https://api.cerebras.ai/v1",
                     {"input": 0.35, "output": 0.75, "cache_read": 0.35}, 128_000),
    "flash-lite": ("gemini", "gemini", "gemini-3.5-flash-lite", None,
                   {"input": 0.0, "output": 0.0, "cache_read": 0.0}, 1_048_576),
    "nemotron-super": ("nvidia_nim", "nvidia", "nvidia/nemotron-3-super-120b-a12b",
                       "https://integrate.api.nvidia.com/v1",
                       {"input": 0.0, "output": 0.0, "cache_read": 0.0}, 128_000),
    "or-lightning": ("open_router", "openrouter", "nvidia/nemotron-3.5-lightning:free",
                     "https://openrouter.ai/api/v1",
                     {"input": 0.0, "output": 0.0, "cache_read": 0.0}, 1_000_000),
    "sonnet": ("anthropic", "anthropic", "claude-sonnet-5-5", None,
               {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50}, 1_000_000),
    "opus": ("anthropic", "anthropic", "claude-opus-5-5", None,
             {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00}, 1_000_000),
    "ministral-8b": ("mistral", "mistral", "ministral-8b-2512", "https://api.mistral.ai/v1", None, 262_144),
    "ministral-14b": ("mistral", "mistral", "ministral-14b-2512", "https://api.mistral.ai/v1", None, 262_144),
    "mistral-medium": ("mistral", "mistral", "mistral-medium-2604", "https://api.mistral.ai/v1", None, 262_144),
    "mistral-large": ("mistral", "mistral", "mistral-large-2512", "https://api.mistral.ai/v1", None, 262_144),
    "magistral-small": ("mistral", "mistral", "magistral-small-latest", "https://api.mistral.ai/v1", None, 262_144),
    "codestral": ("mistral", "mistral", "codestral-2508", "https://api.mistral.ai/v1", None, 256_000),
    "flash": ("gemini", "gemini", "gemini-3.5-flash", None, None, 1_048_576),
    "gemini-pro": ("gemini", "gemini", "gemini-3.1-pro-preview", None, None, 1_048_576),
    "gemma-31b": ("gemini", "gemini", "gemma-4-31b-it", None, None, 262_144),
    "or-nemotron-ultra": ("open_router", "openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free",
                          "https://openrouter.ai/api/v1", {"input": 0.0, "output": 0.0, "cache_read": 0.0}, 1_000_000),
    "or-gemma-31b": ("open_router", "openrouter", "google/gemma-4-31b-it:free",
                     "https://openrouter.ai/api/v1", {"input": 0.0, "output": 0.0, "cache_read": 0.0}, 262_144),
    "or-inkling": ("open_router", "openrouter", "thinkingmachines/inkling:free",
                   "https://openrouter.ai/api/v1", {"input": 0.0, "output": 0.0, "cache_read": 0.0}, 1_048_576),
    "or-laguna-s": ("open_router", "openrouter", "poolside/laguna-s-2.1:free",
                    "https://openrouter.ai/api/v1", {"input": 0.0, "output": 0.0, "cache_read": 0.0}, 262_144),
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--env", type=Path, required=True)
    p.add_argument("--home", type=Path, default=HERE / "home")
    args = p.parse_args()
    env = read_env(args.env)
    models = {}
    for name, (provider, backend, model_id, base_url, cost, window) in MODELS.items():
        entry: dict[str, object] = {
            "backend": backend,
            "model": model_id,
            "api_key": key_for(provider, env),
            "context_window": window,
            "max_tokens": 32 * 1024,
        }
        if cost is not None:
            entry["cost"] = cost
        if base_url:
            entry["base_url"] = base_url
        models[name] = entry
    tau = args.home / ".tau"
    tau.mkdir(parents=True, exist_ok=True)
    config = {
        "models": models,
        "default_model": "claude-haiku-5-5",
        "compaction": {"summarizer": "flash-lite"},
        "extensions": {
            "router": {
                "profiles": {
                    "budget-target": ["claude-haiku-5-5", "mistral-small", "ministral-3b", "nemotron-super",
                                      "flash-lite"],
                    "free-only": ["nemotron-super", "flash-lite", "or-nemotron-ultra", "or-inkling", "or-gemma-31b",
                                  "or-laguna-s", "or-lightning"],
                },
                "profile": "budget-target",
                "budgets": {"anthropic": {"cost": 0.25, "period": "day"}, "mistral": {"cost": 0.25, "period": "day"},
                            "cerebras": {"cost": 0.05, "period": "day"}},
                "reserve_cost": 0.001,
            },
            "planner": {},
        },
    }
    (tau / "config.json").write_text(json.dumps(config, indent=1))
    # The extensions load from the installed package (drive.sh passes `tau-router ext-args`), so the
    # links earlier versions put in extensions/ are removed rather than left to load a second copy.
    for name in ("router.py", "planner.py"):
        (tau / "extensions" / name).unlink(missing_ok=True)
    # /plan is a prompt template, and Tau 0.13 reads templates only from its prompt dirs (john/tau #39).
    # The sandbox links the packaged one in; a real install does the same by hand.
    prompts = tau / "prompts"
    prompts.mkdir(exist_ok=True)
    (prompts / "plan.md").unlink(missing_ok=True)
    (prompts / "plan.md").symlink_to(prompt_dir() / "plan.md")
    (tau / "config.json").chmod(0o600)
    print(f"wrote {tau / 'config.json'} with {len(models)} models: {', '.join(models)}")
    unused = sorted(set(KEY_ENV) - {m[0] for m in MODELS.values()})
    if unused:
        print("providers without a model:", unused)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
