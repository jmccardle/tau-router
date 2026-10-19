"""Probe prompt-cache behavior and usage reporting per provider, over raw HTTP.

A long stable system prefix plus a growing conversation, with configurable
delays between turns. Every call appends one JSON line (raw usage, latency,
rate-limit headers) to the output file, and a shared spend ledger caps each
provider at the authorized experiment budget.

    python experiments/cache_probe.py --env PATH/TO/.env \
        --provider anthropic --delays 0,2,10,30,0,90,330,0
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import httpx

# Experiment budget per provider, authorized 2026-10-14.
MAX_USD = 1.00
MAX_TOKENS = 1_000_000

# provider -> (model, USD per M input, USD per M output); list prices or OpenRouter's as a stand-in.
TARGETS: dict[str, tuple[str, float, float]] = {
    "anthropic": ("claude-haiku-5-5", 0.10, 0.50),
    "cerebras": ("qwen-3.8-27b", 0.99, 1.49),
    "gemini": ("gemini-3.5-flash-lite", 0.30, 2.50),
    "mistral": ("mistral-small-2603", 0.15, 0.60),
    "nvidia_nim": ("nvidia/nemotron-3-super-120b-a12b", 0.0, 0.0),
    "open_router": ("nvidia/nemotron-3.5-lightning:free", 0.0, 0.0),
}

KEY_ENV = {
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_API_API_KEY"),
    "cerebras": ("CEREBRAS_API_KEY",),
    "gemini": ("GEMINI_API_KEY",),
    "mistral": ("MISTRAL_API_KEY", "MISTRAL_KEY"),
    "nvidia_nim": ("NVIDIA_NIM_API_KEY",),
    "open_router": ("OPENROUTER_API_KEY",),
}

OPENAI_BASE = {
    "cerebras": "https://api.cerebras.ai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "nvidia_nim": "https://integrate.api.nvidia.com/v1",
    "open_router": "https://openrouter.ai/api/v1",
}

HERE = Path(__file__).resolve().parent
LEDGER = HERE / "out" / "spend.jsonl"


def read_env(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; quotes stripped; comments ignored."""
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip().removeprefix("export ").strip()] = v.strip().strip("'\"")
    return env


def key_for(provider: str, env: dict[str, str]) -> str:
    for name in KEY_ENV[provider]:
        if env.get(name):
            return env[name]
    raise SystemExit(f"no key for {provider}: set one of {KEY_ENV[provider]}")


def manual(n_rules: int = 420, seed: int = 7) -> str:
    """A deterministic fictional station manual, long enough to cross every cache minimum."""
    rng = random.Random(seed)
    nouns = "valve hatch relay pump lattice beacon ledger quorum filter spindle conduit array gasket".split()
    verbs = "inspect seal vent log rotate calibrate purge certify isolate flush tag escalate".split()
    when = "at dawn|after any alarm|before shift change|weekly|when pressure drops|on request".split("|")
    lines = ["You are the duty officer of Tessaract Station. The station manual follows.", ""]
    for i in range(1, n_rules + 1):
        lines.append(
            f"Rule {i}: {rng.choice(verbs).capitalize()} the {rng.choice(nouns)} {rng.choice(when)}; "
            f"if it fails, {rng.choice(verbs)} the {rng.choice(nouns)} and notify deck {rng.randint(1, 9)}."
        )
    lines += ["", "Answer questions about the manual in one short sentence."]
    return "\n".join(lines)


def spent(provider: str) -> tuple[float, int]:
    usd, tokens = 0.0, 0
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            row = json.loads(line)
            if row["provider"] == provider:
                usd += row["usd"]
                tokens += row["tokens"]
    return usd, tokens


def charge(provider: str, usd: float, tokens: int, tag: str) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps({"ts": time.time(), "provider": provider, "usd": usd, "tokens": tokens, "tag": tag}) + "\n")


RATE_HEADER_PREFIXES = ("x-ratelimit", "anthropic-ratelimit", "retry-after", "x-request-id", "request-id", "cf-ray")


def keep_headers(h: httpx.Headers) -> dict[str, str]:
    return {k: v for k, v in h.items() if k.lower().startswith(RATE_HEADER_PREFIXES)}


def call(provider: str, key: str, model: str, system: str, msgs: list[dict[str, str]], max_out: int) -> tuple[int, dict, dict, str]:
    """One request; returns (status, raw json, kept headers, reply text)."""
    if provider == "anthropic":
        body_msgs = [{"role": m["role"], "content": [{"type": "text", "text": m["content"]}]} for m in msgs]
        # Rolling breakpoint on the newest message, plus one on the system prefix.
        body_msgs[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={
                "model": model,
                "max_tokens": max_out,
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                "messages": body_msgs,
            },
            timeout=120,
        )
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict))
        return r.status_code, data, keep_headers(r.headers), text
    if provider == "gemini":
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in msgs]
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": contents,
                "generationConfig": {"maxOutputTokens": max_out},
            },
            timeout=120,
        )
        data = r.json()
        parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        return r.status_code, data, keep_headers(r.headers), "".join(p.get("text", "") for p in parts)
    body: dict = {"model": model, "max_tokens": max_out, "messages": [{"role": "system", "content": system}, *msgs]}
    if provider == "open_router":
        body["usage"] = {"include": True}
    r = httpx.post(
        f"{OPENAI_BASE[provider]}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=body,
        timeout=120,
    )
    data = r.json()
    choice = (data.get("choices") or [{}])[0].get("message") or {}
    return r.status_code, data, keep_headers(r.headers), choice.get("content") or ""


def usage_of(provider: str, data: dict) -> dict:
    """Normalized counts: input (uncached), cache_read, cache_write, output (incl. reasoning)."""
    if provider == "anthropic":
        u = data.get("usage") or {}
        return {
            "input": u.get("input_tokens", 0),
            "cache_read": u.get("cache_read_input_tokens") or 0,
            "cache_write": u.get("cache_creation_input_tokens") or 0,
            "output": u.get("output_tokens", 0),
        }
    if provider == "gemini":
        u = data.get("usageMetadata") or {}
        cached = u.get("cachedContentTokenCount") or 0
        return {
            "input": u.get("promptTokenCount", 0) - cached,
            "cache_read": cached,
            "cache_write": 0,
            "output": (u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0),
        }
    u = data.get("usage") or {}
    cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
    return {
        "input": u.get("prompt_tokens", 0) - cached,
        "cache_read": cached,
        "cache_write": 0,
        "output": u.get("completion_tokens", 0),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--env", type=Path, required=True)
    p.add_argument("--provider", choices=sorted(TARGETS), required=True)
    p.add_argument("--model", help="override the default small model")
    p.add_argument("--delays", default="0,2,10,30,0,90,330,0", help="seconds to wait before each turn")
    p.add_argument("--rules", type=int, default=420, help="manual length; ~19 tokens per rule")
    p.add_argument("--max-out", type=int, default=200)
    p.add_argument("--tag", default="cache")
    args = p.parse_args()

    model, price_in, price_out = TARGETS[args.provider]
    model = args.model or model
    key = key_for(args.provider, read_env(args.env))
    system = manual(args.rules)
    out = HERE / "out" / f"{args.tag}-{args.provider}-{int(time.time())}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.provider)
    msgs: list[dict[str, str]] = []

    for turn, delay in enumerate(float(d) for d in args.delays.split(",")):
        usd, toks = spent(args.provider)
        if usd >= MAX_USD or toks >= MAX_TOKENS:
            print(f"{args.provider}: experiment budget reached (${usd:.4f}, {toks} tokens); stopping", file=sys.stderr)
            break
        time.sleep(delay)
        msgs.append({"role": "user", "content": f"What does rule {rng.randint(1, args.rules)} say?"})
        t0 = time.monotonic()
        status, data, headers, text = call(args.provider, key, model, system, msgs, args.max_out)
        latency = time.monotonic() - t0
        u = usage_of(args.provider, data) if status == 200 else {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0}
        # Charge cache reads/writes at full input price: an upper bound until per-provider cache prices are known.
        tokens = sum(u.values())
        usd_call = (u["input"] + u["cache_read"] + u["cache_write"]) * price_in / 1e6 + u["output"] * price_out / 1e6
        charge(args.provider, usd_call, tokens, args.tag)
        row = {
            "turn": turn, "delay": delay, "status": status, "latency_s": round(latency, 3), "model": model,
            "usage": u, "usd_upper": usd_call, "headers": headers,
            "raw_usage": data.get("usage") or data.get("usageMetadata"),
            "error": None if status == 200 else data, "reply": text[:200],
        }
        with out.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"{args.provider} t{turn} +{delay:>4.0f}s {status} {latency:5.2f}s in={u['input']} "
              f"read={u['cache_read']} write={u['cache_write']} out={u['output']}")
        if status != 200:
            break
        msgs.append({"role": "assistant", "content": text or "(no text)"})
    print(f"{args.provider}: wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
