# Test drive: router + planner on Tau master

Everything runs against a sandbox HOME (`experiments/home`), so your real `~/.tau`
(models, jmfts session store, extensions) is never read or written.

## Setup (done once; rerun after editing keys or models)

```sh
cd tau-router/experiments                   # this repo's experiments/
tau-master/venv/bin/pip install -e ..        # tau-router into Tau's venv, once
../venv/bin/python make_tau_home.py --env PATH/TO/.env    # a .env holding your provider keys
```

This writes `home/.tau/config.json` with 22 models across six providers, and the
`router` and `planner` extension config. Every model is in the `/model` picker.
Models without a `cost` block (the larger Mistral and Gemini models)
are unpriced: you can pick them directly, but the router refuses them under a
budget rather than guess a price. The OpenRouter `:free` models are priced at 0,
as OpenRouter's API reports them, and join the `free-only` profile. Context windows
are what each provider's model API reported on 2026-10-16. The extensions load from
the installed package: `drive.sh` and the `run_*.sh` scripts pass `$(tau-router
ext-args)`. Only `/plan`'s template is linked in, into `home/.tau/prompts/`,
because Tau 0.13 can't take one from an extension (john/tau #39). Tau itself is
a private clone at `experiments/tau-master`, with its own venv and the TUI
installed. It is on the 0.13.0 release branch (53ede1e as of 2026-10-18).

## Drive

```sh
cd ~/some/project && PATH/TO/tau-router/experiments/drive.sh   # TUI where you are
./drive.sh --fixture          # TUI in a fresh copy of fixtures/e6 (three modules, check.py)
./drive.sh -p "question"      # headless, one shot, in the current directory
```

### Commands

| command | what it does |
|---|---|
| `/models` | every configured model grouped by provider, with its price per M tokens (or "unpriced"/"free"), and which profile rungs it fills; `>` marks the current one |
| `/model <name>` | Tau's own picker. The router treats your pick as **pinned** and stops choosing for you, until you run `/profile` or `/tier`, or that model is blocked (on hold, or its provider's budget is spent). You can pin an unpriced model; its calls are counted but carry no dollars |
| `/budget` | spending this period per provider against its cap, calls today, unpriced calls, the profile's rungs with any block reason, and planner slices |
| `/profile [name]` | list the profiles, or switch to one, which also resumes routing after a pin |
| `/tier [rung]` | show or set the highest rung the router may use, e.g. `/tier mistral-small` keeps you off Haiku |
| `/plan <goal>` | a prompt template (`src/tau_router/prompts/plan.md`). The current model plans, then hands parts to sub-agents through the `delegate` tool |

To "pick by provider", use `/models` to see the names under each provider, then
`/model <name>`. There's no provider-level setting yet: budgets are per
provider, and choices are per model.

### What happens on its own

- **Routing:** unpinned, you're on the `budget-target` profile (claude-haiku-5-5 →
  mistral-small → ministral-3b → nemotron-super → flash-lite). When a provider's
  daily budget runs low, or a model gets a 429, the router moves you down a rung
  *on the next request*. The conversation keeps going, and a `[router]` note
  marks the switch.
- **Delegation:** `delegate` is a tool for the model, not for you. You start it
  with `/plan`, or by asking for delegation in plain words. Each part becomes a
  sub-agent with its own model, budget slice and shell done-check.
  - Parts that don't depend on each other run in parallel.
  - A failed check is retried once, one rung up.
  - `/budget` lists the slices.
- **`budget_status`:** the same information as `/budget`, as a tool any model
  can call.
- **Status strip (TUI):** after each turn, `router: <model> [provider] · <profile or
  pinned> $spent/$cap period` in Tau's extension status line (`ctx.ui.set_status`).

## Knobs (`home/.tau/config.json` → `extensions.router`)

| key | what it does |
|---|---|
| `profiles`, `profile` | the ordered model lists and the active one (`free-only` is also defined) |
| `tier` | the highest rung allowed, e.g. `"mistral-small"` keeps you off Haiku |
| `budgets` | per provider: `{cost, period: day/month/once, anchor_day, since}`. Defaults: Anthropic and Mistral $0.25/day, Cerebras $0.05/day. Gemini and NIM are free and have no budget |
| `persona_cost` | an optional cap on all spending together |
| `currency` | the symbol amounts are shown with (default `$`); nothing is converted |
| `mode` | `"agent"` adds the `select_model` tool, so the model chooses its own rung |

The ledger is `home/.tau/ext-state/tau-router.jsonl`. Summarize a run with
`../venv/bin/python plan_report.py <dir containing ledger.jsonl and events.jsonl>`.
The headless runs in `out/` have both files; for a TUI run, copy the ledger
next to an `events.jsonl`, or just read the JSONL.

## Known rough edges

- **Children's context is your seeded design:** the parent's assignment, then
  a `[router]` model-switch note, then a `start_subagent` call with the brief as
  its result. Children get their own keys (Tau d68156a).
- **Recursion works (`subplanner: true`),** with nested budget slices, but the
  decompositions get sloppy two levels down.
- **A slice can overshoot by one call,** because the router stops a branch at
  `turn_end`, after the spend.
- **`set_reasoning`:** unreliable across providers (#22), so rungs don't set a
  reasoning level.
- **Cost:** on these small tasks a Haiku planner costs about $0.006 of a
  $0.012–0.015 run, roughly 4× doing the job directly with Haiku (about $0.003).
  Delegation should pay off on jobs too large for one context, or with a cheaper
  planner. Neither has been measured yet.
