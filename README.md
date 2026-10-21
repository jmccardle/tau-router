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

**Status: working toward 1.0** (see `ROADMAP.md`). `master` runs on Tau 0.14;
the 0.1.0 release on PyPI is for Tau 0.13. Spend is tracked per process, so two
Tau instances don't yet see each other's spending; the shared ledger fixes that.

## Install and load

```sh
pip install ffwf-tau                        # Tau 0.14, from PyPI
pip install ffwf-tau-router                 # into the same environment as Tau
tau ext authorize tau_router.router         # once per installed version
tau ext authorize tau_router.planner
tau                                         # finds and loads both
```

Tau finds both extensions through the package's entry points, and loads one only
after you authorize it. Upgrading tau-router means authorizing again. The TUI
asks; `tau -p`, `--mode rpc` and `tau serve` never ask, and print one line naming
each extension they skipped. `tau ext list` shows what would load.

**A router that fails to load leaves your spending unbudgeted.** Tau shows a notice
and keeps going without it. If you need the guarantee, name it on the command
line: `tau -e tau_router.router -e tau_router.planner`. An extension named with
`-e` is authorized by being named, and if it fails to load, Tau stops.

If you pass `--tools`, it is an allowlist over every tool, the extensions' too:
name `delegate`, `budget_status` and (in agent mode) `select_model`, or they're
left out.

`/plan <goal>` is a prompt template that ships in the package. Tau reads
templates only from its prompt directories (john/tau #39). Until #39 lands, link
it in yourself if you want it:

```sh
ln -s "$(tau-router prompt-dir)/plan.md" ~/.tau/prompts/plan.md
```

`delegate` works without the template. Asking for delegation in plain words is
enough.

## Configure

The router reads `extensions."tau_router.router"` in Tau's `config.json`. Its
name is the full module name, dots included:

```json
"tau_router.router": {
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

On the command line, `--ext-config tau_router.router:profile=free-only` sets one
key for a run; `:` separates the extension's name from the key, and the value is
read as JSON when it parses as JSON.

Config keys from before 0.1 (`usd`, `persona_usd`, `reserve_usd`) are refused,
with a message naming each key's new name.

### Upgrading from 0.1 (Tau 0.13)

- Rename `extensions.router` to `extensions."tau_router.router"`, and
  `extensions.planner` to `extensions."tau_router.planner"`. **Until you do, the
  router fails to load, and nothing you spend is budgeted.** The failure names the
  old key.
- `--ext-config router.KEY=VALUE` becomes `--ext-config tau_router.router:KEY=VALUE`.
  Tau refuses the old form at startup.
- `tau-router ext-args` is gone; authorize the extensions instead (above).

## When a rung can't be used

The router skips a rung, and goes on to the next one, when:

- its provider's budget is spent, or what's left is below `reserve_cost`;
- the model is held after a 429, 503 or 529 (for its Retry-After, or `hold_seconds`);
- Tau can't build its config entry, or the name isn't one of Tau's models;
- its provider refused the request with a 401 or 403 ("no API key", "API key
  refused").

The last two last until Tau restarts, since they need a config or key fix.
`/budget` shows each rung's reason. What keeps the router from routing normally
(a spent budget, a skipped model, a pin, or every rung blocked) is also a Tau
session warning: in the TUI footer, in `/extensions`, and over RPC.

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
<spent>/<cap> <period>`, from the start of the session.

## Tests

`pip install -e '.[dev]' && pytest`. The tests run the extensions against a fake
Tau api and ctx with scripted turns. No model is called. `python -I
tests/check_loader.py` runs the installed `tau` on the installed package, in a
throwaway home. `experiments/` holds
the live runs, results (`FINDINGS.md`) and a sandbox for trying it
(`TEST-DRIVE.md`). `CONTRIBUTING.md` covers the checks, remotes and releases.

## License

MIT.
