# tau-router

Two [Tau](https://dev.ffwf.net/forgejo/john/tau) extensions for spending across
several LLM accounts on a budget:

- **router** picks the model for each request from a *profile*: an ordered list,
  best first. It moves down a rung when a provider's budget runs low or a model is
  rate-limited, and back up when the block clears. A model you pick with `/model`
  is *pinned* until you resume routing.
- **planner** gives the model a `delegate` tool. Each part of a job runs as a
  sub-agent on its own model, with its own budget slice and a shell command that
  says when it's done. A failed check is retried once, one rung up.

**Status: 0.0.1, working toward 1.0** (see `ROADMAP.md`). It works on Tau 0.13.0.
Spend is tracked per process, so two Tau instances don't yet see each other's
spending; 0.2 fixes that.

## Install and load

```sh
pip install ffwf-tau                        # Tau 0.13.0 or later, from PyPI
pip install ffwf-tau-router                 # into the same environment as Tau
tau $(tau-router ext-args)                  # loads router and planner
```

Tau 0.13 loads extensions only from files, so `tau-router ext-args` prints a
`-e <path>` for each installed module. Nothing is copied into `~/.tau`. The
package also declares `tau.extensions` entry points, which Tau will read once
john/tau #35 lands. Then `tau` alone finds the extensions, and you enable them in
config.

`/plan <goal>` is a prompt template that ships in the package. Tau 0.13 reads
templates only from its prompt directories (john/tau #39). Until #39 lands, link
it in yourself if you want it:

```sh
ln -s "$(tau-router prompt-dir)/plan.md" ~/.tau/prompts/plan.md
```

`delegate` works without the template. Asking for delegation in plain words is
enough.

## Configure

The router reads `extensions.router` in Tau's `config.json`:

```json
"router": {
  "profiles": {"budget": ["claude-haiku-5-5", "mistral-small", "nemotron-super"],
               "free-only": ["nemotron-super", "flash-lite"]},
  "profile": "budget",
  "budgets": {"anthropic": {"cost": 3.00, "period": "month", "anchor_day": 8},
              "mistral":   {"cost": 5.00, "period": "month", "anchor_day": 1},
              "cerebras":  {"cost": 15.00, "period": "once"}},
  "currency": "$"
}
```

- **Profile names are model names from `models`.** The router prices each call
  with that model's `cost` block, the prices per million tokens.
- **A budget is a cap on what this router spends with a provider in each period:**
  `day`, `month` from `anchor_day` (the day of the month it resets, 1–31, in
  UTC; default 1; in a month too short for it, the last day), or `once` since
  `since`. Your other tools share these accounts, so
  the cap is an allowance, not a balance.
- **`cost` amounts are in whatever currency your prices are written in.**
  `currency` is only the display symbol, and nothing is converted.
- **A model with no `cost` block is unpriced.** You can pin it by hand, but the
  router won't route to it under a budget.

Other keys:

| key | default | what it does |
|---|---|---|
| `tier` | the first rung | the highest rung the router may use |
| `persona_cost` | none | a cap on all spending together |
| `reserve_cost` | 0.002 | the headroom a priced rung needs to be chosen |
| `mode` | `"auto"` | `"agent"` adds `select_model`, so the model chooses its own rung |
| `hold_seconds` | 60 | how long a refused model is held when the refusal has no Retry-After |
| `ledger` | `<tau home>/ext-state/tau-router.jsonl` | where spending is recorded |

Config keys from before 0.1 (`usd`, `persona_usd`, `reserve_usd`) are refused,
with a message naming each key's new name.

## Commands and tools

| | what it does |
|---|---|
| `/budget` | spend per provider against its cap, the profile's rungs and why any is blocked, and planner slices |
| `/models` | every configured model by provider, with its price and profile rungs |
| `/profile [name]` | list profiles, or switch, which also resumes routing after a pin |
| `/tier [rung]` | show or set the highest rung |
| `budget_status` (tool) | the same as `/budget`, as JSON for the model |
| `delegate` (tool) | run one part as a budgeted sub-agent (planner) |

In the TUI, the status strip shows `router: <model> [provider] · <profile or pinned>
<spent>/<cap> <period>`.

## Tests

`pip install -e '.[dev]' && pytest`. The tests run the extensions against a fake
Tau api and ctx with scripted turns. No model is called. `experiments/` holds
the live runs, results (`FINDINGS.md`) and a sandbox for trying it
(`TEST-DRIVE.md`).

## License

MIT.
