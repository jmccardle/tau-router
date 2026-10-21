# Roadmap

## What tau-router is (decided 2026-10-18)

tau-router is a **Tau extension package**: the `router` and `planner` extensions, plus
a small library they import for prices, the catalog, the ledger and budget periods.
Several Tau processes can run at once against the same accounts, so all shared state
lives in one ledger that every instance reads and writes.

The HTTP proxy that the 0.0.1 core was built toward is not part of 1.0 (see "Not in
1.0").

## Status (2026-10-21)

- **`master` runs on Tau 0.14.0** ("On Tau 0.14.0" below); it is not released yet.
- **Version:** 0.1.0, tagged `v0.1.0` and published to PyPI as `ffwf-tau-router`
  (the import stays `tau_router`). `/plan` is linked in by hand until john/tau #39
  lands. The session's TUI drive of the status strip served as the 0.1 check; John's
  own drive is the 1.0 sign-off.
- **Next:** release the Tau 0.14 port, then 0.2, the shared SQLite ledger.
- **Installs from PyPI** (2026-10-18). The 0.13.0 dists (`ffwf-tau`,
  `ffwf-tau-agent-core`, `-coding-agent`, `-llm`) are published. A fresh venv with
  those from PyPI, plus a tau-router wheel and no Tau checkout, gave:
  - 27/27 tests pass against the installed package.
  - `tau -p -m claude-haiku-5-5 $(tau-router ext-args)` loaded both extensions.
    One Haiku 5.5 turn cost $0.000616, which matches Anthropic's published
    prices. A headless `/budget` printed the spend.
  - In the TUI, `/budget` sent as the first line of the startup screen showed
    the budget with no model call: `AgentSession.submit` resolves it again once
    the session exists. Only the editor's hint and completion are wrong there
    (#42).
- **Publishing** (approved 2026-10-18; not tagged yet): `ffwf-tau-router` on PyPI from
  github.com/jmccardle/tau-router. `.github/workflows/publish.yml` runs tests on
  Python 3.11–3.14, ruff, mypy, Tau's real loader (`tests/check_loader.py`), a
  version-vs-tag check and `twine check --strict`. It publishes to TestPyPI on a
  manual dispatch and to PyPI on a `v*` tag, through trusted publishing. All four
  versions passed those steps in python:<v>-bookworm containers. 0.1 caps
  `ffwf-tau-agent-core<0.14`, because Tau 0.14 renames extensions.
- **Cerebras is priced** (Developer Tier, 2026-10-18): gpt-oss-120b $0.35 in / $0.75 out
  and qwen-3.8-27b $0.99 / $1.49 per M. A live turn on each matched its ledger cost.
- **Test model:** `claude-haiku-5-5`, named by its API id. The
  sandbox, the run scripts and the README use that key.
- **Open decisions** are in "Inputs needed from John". **External blockers** are
  in "Tau dependencies".

## 1.0: the three user stories

| story | 1.0 means |
|---|---|
| **Several providers, some serving the same model** | A profile rung names a *model*, such as `gemma-31b` or `nemotron-super`, not a provider entry. The router picks the provider that serves it. It stays on the current provider while that one is unblocked (its cache is warm), then moves to the cheapest unblocked provider. `/models` groups providers under each model. |
| **A session budget that stops work, or drops to free models, when it's spent** | `session_cost` and `on_exhausted: "stop" \| "free"`. `/budget session 0.50` sets the budget for the running session. The status strip shows what's left. When the budget is spent, the current run ends at the next turn boundary with a `[router]` note; no task is handed mid-way to a weaker model. With `stop` (the default), later prompts are refused until `/budget raise`; with `free`, they route to the `free-only` profile. No request ever overshoots the cap (needs Tau #28). |
| **Split the budget between sub-agents, track their spend, re-split what's left** | The session account is the root of the budget tree. Each sub-agent's slice is a child account. A child's unspent money returns to its parent when it finishes. A plan can give its later steps *shares* rather than dollar amounts: when a step starts, its slice is its share of whatever is left. `/budget` and a live panel show the tree: spent, cap and state per node. |

Across all three stories:
- **Amounts are `cost`, not `usd`.** Prices and budgets are plain numbers in one
  currency per config, the one your providers bill you in. `currency` (default `"$"`)
  is only the display symbol. Converting between currencies is out of scope: a
  provider billed in another currency is priced in yours by hand.
- **Shared accounts are allowances, not balances.** The router caps only its own
  spending, and `/budget raise` and `/budget reset` adjust a cap. Where a provider
  reports a balance, the effective limit is the lower of the remaining allowance and
  the polled balance.
- **Several instances at once:**
  - Provider allowances and holds are global, so two Tau processes see each other's
    spend and 429s.
  - Session budgets, pins and slices belong to their session, and survive
    `--continue`.

## Milestones

### 0.1.0 An installable extension package

Tau 0.14.0 ships tau-router as one of its two headline extensions, loaded through
the entry-point interface of john/tau #35 (tau-arecibo, 2026-10-18). So 0.1 makes
it a normal pip distribution: it depends only on `ffwf-tau-agent-core>=0.13.0`,
never on a Tau checkout, and nothing is copied into `~/.tau`.

What 0.1 contains:
- `tau_router.ext.router` and `tau_router.ext.planner` are the modules Tau loads,
  each one line that imports `register` from `tau_router.router` or
  `tau_router.planner`. Tau 0.13 loads `-e` files under a synthetic module name,
  so the code stays in modules imported by their real names and exists once.
- The entry points are declared under the group `tau.extensions` (provisional
  until #35 is built). They name `tau_router.router` and `tau_router.planner`,
  because John decided on #35 (comment 6634) that an extension's identifier is its
  module name. Those are the names config and the UI will show. Until then, `tau $(tau-router ext-args)` loads both from
  wherever pip installed them.
- The 0.0.1 proxy core is removed: its config, catalog, selector, budget layers,
  ledger, CLI and their 59 tests. Its stacked free/promo/paid
  layers come back in 0.4 as stacked allowances.
- `usd` became `cost` everywhere: `budgets.<p>.cost`, `persona_cost`,
  `reserve_cost`, `delegate`'s `budget_cost`, and `cost` on ledger rows, which
  moved to `tau-router.jsonl`. `currency` sets the display symbol. Old keys are
  refused with a message naming each key's new name.
- The router finds Tau's home through `resolve_tau_home()`, not `~/.tau`.
- 27 fixture tests against a fake api and ctx cover routing, step-downs and
  refusal, per-cursor step-downs, pins, holds, slices and nested slices,
  unpriced models, renamed keys, the status strip, `budget_status`, and the
  planner's slices, escalation and refusals. Other tests check the entry points,
  `ext-args` and the packaged template. ruff and mypy are clean.
- Live: fixtures/e6 on Tau 0.13.0, loaded from the installed package, printed
  ALL PASS for $0.0126 (`experiments/out/pkg-e6`).

Released as 0.1.0:
- `/plan` is a template in the package, but Tau 0.13 can't take a template from
  an extension (john/tau #39), so you link it in by hand. The sandbox does.
  0.1.0 shipped with the manual link.
- The status strip was checked with the session's own tmux TUI drive, which also
  found Tau #42 (on the startup screen, the editor said extension commands go to
  the model and completed none of them).
- Dropped: splitting the pure decisions out of the hooks. The fake-ctx tests
  drive the hooks directly, so the split bought no testability.

### On Tau 0.14.0 (on `master`, not released)

Tau 0.14.0 is on PyPI (v0.14.0 = b016dff, 2026-10-21). `master` now requires
`ffwf-tau-agent-core>=0.14.0,<0.15`. The release number and its timing are John's
call ("Inputs needed from John").

Names. John decided the #35 spelling on 2026-10-18: the full dotted module name
everywhere, with `:` as the delimiter.

| site | 0.1.0 (Tau 0.13) | `master` (Tau 0.14) |
|---|---|---|
| planner finds the router | `ext:planner:need_router` | `ext:tau_router.planner:need_router` |
| config | `extensions.router`, `extensions.planner` | `extensions."tau_router.router"`, `extensions."tau_router.planner"` |
| `--ext-config` | `router.KEY=VALUE` | `tau_router.router:KEY=VALUE` |
| loading | `tau $(tau-router ext-args)`, through `tau_router/ext/` | discovered through the entry points, after `tau ext authorize` |

What changed:
- `tau_router/ext/` and `tau-router ext-args` are removed. `tau-router prompt-dir`
  stays until #39.
- A router with no config names the key it wants. If `extensions.router` is still
  in config.json, the error says to rename it. Live on 0.14.0, a stale key meant the
  router failed to load, Tau ran on without it, and `/budget` went to the model as
  a prompt. The README says this plainly, and says to use `-e tau_router.router`
  when a load failure must stop the run.
- **A rung Tau won't switch to is skipped, not run over budget.** `ctx.set_model`
  raises `KeyError` (not a configured model) or `ModelUnavailableError` (an entry
  that doesn't build, #65). The router marks that rung unusable with the reason,
  and asks again for the next rung. That covers turn start, a step-down at
  `turn_end`, branch start, `/profile` and `/tier`. Uncaught, this raise ran the
  turn on the over-budget rung (Tau f81e361, #29).
- **A 401 or 403 makes the rung unusable.** The reason comes from
  `error_detail.key_sent`: "no API key", "API key refused", or "refused" when the
  provider doesn't say. The router now records the model each request goes to when
  it sets one, so a refusal is charged to that model, not to the one that answered
  last.
- Unusable rungs are kept in memory, not in the ledger, so a fixed config or key
  works after a restart.
- **Session warnings (#60):** a spent provider budget or overall cap (warning), a
  skipped model (warning), a pin (warning), and every rung blocked (error). Each
  is set when it starts holding, cleared when it ends, and not set again while
  unchanged. Messages carry no amounts, so they don't re-notify on every call.
- **A new conversation drops the pin.** `/new`, fork and resume fire no hook in
  0.14, so the router compares `ctx.session_id` at each input.
- The status strip is painted at `session_start`, because the TUI opens its
  session at mount (#42).
- `make_tau_home.py` authorizes both extensions in the sandbox. The headless
  run scripts name them with `-e`. `drive.sh` lets Tau discover them.
- `tests/check_loader.py` drives the installed `tau` in a throwaway home:
  - both extensions are found unauthorized, then authorized;
  - `tau --verbose -p /budget` answers from the router, with no orphan
    subscription (#44);
  - with the planner disabled, the router's `need_router` subscription is flagged.
  It passes from a clean, non-editable install. `[dev]` adds
  `ffwf-tau-coding-agent` for the CLI.
- Tests: 44 pass (the new ones cover each case above), and ruff and mypy are clean.
- Live on Tau v0.14.0 (2026-10-21):
  - fixtures/e6 `/plan` with a claude-haiku-5-5 planner printed ALL PASS for
    $0.0254, with nothing on stderr. One slice ran over by one call ($0.0102 of
    $0.0100), the known overshoot.
  - TUI drive: the status strip shows at startup, and `/bud` completes there.
    The strip loses `[anthropic]` to markup (#81).

### 0.2.0 One shared ledger

- The ledger moves to SQLite in WAL mode at `~/.tau/ext-state/tau-router.db`, replacing
  the JSONL file, which is read in full on every check.
- Rows carry `session_id` (`ctx.session_id`), `cursor_id` and `account`. Accounts and
  pins are persisted rows, not memory, so `--continue` resumes them.
- Account labels are scoped by session, so two sessions that both delegate a `root/x`
  don't collide.
- Test: two processes write to one ledger at once, and each sees the other's spend
  and holds.

### 0.3.0 Overlapping providers

- In config, a model lists the provider entries that serve it. The catalog suggests
  these equivalences, and you confirm them, as the 0.0.1 design had it.
- The router chooses a provider per request: the current one while unblocked, else
  the cheapest unblocked one. The ledger records both the model and the provider
  entry.
- `/models` groups by model. `/model gemma-31b` pins the model but not a provider.
- Needs Tau #24, so the catalog comes from Tau rather than from reading the config
  file.

### 0.4.0 Session budget and allowances

- `session_cost` (no default: unset means no session cap) and `on_exhausted`
  (`stop`, the default, or `free`).
- **Stacked allowances** for one provider: a recurring promo plus a one-time balance,
  as on Mistral. `/budget` shows each layer. Where the provider bills a card after
  both, the cap you set is the only thing between the router and real money, so a
  priced provider with no cap is refused, not treated as unlimited (free providers
  are marked free, not uncapped).
- `/budget session N`, `/budget raise <provider> N`, and `/budget reset <provider>`:
  `reset` starts a new period and clears a hold after a top-up. Each is an
  `adjustment` row, and no spending row is ever deleted.
- The status strip shows what's left of the session budget and of the current
  provider's allowance.

### 0.5.0 The budget tree

- A child's unspent money returns to its parent. This already holds, because caps are
  ceilings over recorded spend; 0.5 adds tests for it.
- Re-splitting by share: `delegate` takes `share` as an alternative to `budget_cost`.
  The slice is computed when the step starts, from the parent's remaining budget, so
  later steps get what earlier ones left.
- A live panel (`ctx.ui.panel`) shows the tree, and `/budget` prints it.
- A depth cap on sub-planners. FINDINGS §10 showed decompositions getting sloppy
  below two levels.

### 0.6.0 Balances and events

- Balance polling for OpenRouter (`/api/v1/key`). Check whether Anthropic, Cerebras
  and Mistral expose a balance, and record what each can and cannot report.
- Quota headers that show nothing remaining (Anthropic, Cerebras) put a hold on the
  model before the next request.
- Events for other extensions and hosts: `ext:router:spend`, `switched`,
  `budget_low`, `exhausted` and `refused`.

### 1.0.0

- Hard caps: an admission check before each request (Tau #28) refuses a request
  whose estimated worst case exceeds what's left. In SQLite, the check and a
  reservation happen in one transaction, so concurrent instances can't both spend
  the last dollar.
- A handler exception ends the turn (Tau #29). It should never silently stop
  enforcement.
- Cursor cleanup on `cursor_close` (Tau #26), and `cursor_id` on every `agent_end`
  (Tau #27).
- A README user guide built around the three stories. Examples contributed to Tau
  (#30, #31).
- Sign-off: you test-drive each story in the TUI, with two Tau instances sharing the
  account in story 2.

## Tau dependencies

| needed by | Tau | state |
|---|---|---|
| 0.3 | #24 ctx model catalog | filed, after `feat/model-picker` |
| 0.3 (UX) | `feat/model-picker`: `/model` with no session, and the picker form | in progress (as of 2026-10-17) |
| 0.4 (pins) | #25 model changes record their source | filed, after `feat/reasoning-wire` |
| 1.0 | #26 cursor_open/cursor_close for extensions | filed |
| 1.0 | #27 every `agent_end` carries `cursor_id` | filed |
| 1.0 | #28 pre-request admission hook | filed, decision pending |
| 1.0 | #29 an exception in a mutating hook ends the turn | filed |
| 0.1, and Tau 0.14 | #35 extensions from installed packages via entry points; finding an extension is not loading it | filed; the headline of Tau 0.14; tau-router's positions are posted there |
| 0.1 (`/plan`) | #39 an extension cannot contribute a prompt template | filed |
| 0.1 (TUI) | #42 the startup screen had no session, so extension commands didn't complete there | done in 0.14.0: `/bud` completes `/budget` at startup (TUI drive, 2026-10-21) |
| TUI status strip | `ctx.ui.set_status` text is parsed as Textual markup, so the strip's `[anthropic]` disappears | filed as #81 (2026-10-21), after 0.14.1 |
| Tau 0.14 | #35 build: one spelling for dotted module identifiers in `--ext-config`, config keys, `ext:<name>:<topic>` and command owners | done in 0.14.0; tau-router's rename is on `master` |
| 0.1 (typing) | tau_agent_core ships no `py.typed`, so mypy skips its annotations | not filed |
| 0.14 docs | #69 `-m provider/model` with the key only in a config entry dies at the first request with a traceback; the fix is one startup `tau: error:` | filed. Until then the README says: name a configured model (`-m claude-haiku-5-5`), not `anthropic/<id>` |
| 1.x | #22 `set_reasoning`, #23 thinking display and replay: a reasoning level per rung | open |

## Not in 1.0

- The HTTP service and `tau-router send`, for harnesses other than Tau. The selector
  and the account/equivalence design from 0.0.1 would carry over if it comes back.
- A reasoning level per rung (#22, #23).
- Learning $/task per (task kind, rung) to choose a tier.
- Suggesting `/plan` automatically.
- Discord and Telegram front ends via Tau, never `--dangerously-skip-permissions`.

## Done

- **Experiments and prototype** (2026-10-14 to 10-18):
  - The router and planner as Tau extensions, on Tau master c759478.
  - Tau gaps P1–P6, the branch-key fix and seeded `spawn_branch` all landed in Tau.
  - Evidence: `experiments/FINDINGS.md`. Design: `DESIGN.md`. Trying it:
    `experiments/TEST-DRIVE.md`.
  - The extension workarounds map to Tau #24–#31 (`DESIGN.md`).
- **0.0.1 routing core**, since removed: TOML config, catalog and listings, SQLite ledger
  (`attempts`, `cooldowns`), budget layers, selector, and the `refresh`, `models`,
  `suggest` and `route` (dry-run) commands. 59 fixture tests; ruff and
  `mypy --strict` are clean.

## Decided 2026-10-18

- `on_exhausted` defaults to `stop`: stopping for budget is the intended behavior,
  and switching to `free-only` to continue is the user's call.
- No default `session_cost`.
- Amounts are named `cost`, not `usd` (see above).
- License: MIT (`LICENSE`).
- #35 spelling: full dotted module names at every site, `:` as the delimiter, a
  short name only interactively. Drop-in directory extensions go through the same
  authorization as packages, and existing drop-ins are grandfathered.
- #42: Tau 0.14.0 creates the TUI session at mount.
- No "required extension" flag (John, 2026-10-19). An extension doesn't decide for
  the user that it's required, and checking that an extension loads after an install
  or upgrade is the user's job. Tau shows a notice in every head when a discovered
  extension fails to load, and keeps running; an explicit `-e` still fails the run.
  tau-router's code doesn't change; the 0.14 README says what it means for budgets.

## Accounts

The accounts tau-router is built against mix four kinds: a monthly promo that
resets on a fixed day, a one-time prepaid balance, a monthly promo with a
standing balance after which the provider charges a card, and free tiers. In
the last kind, the cap you set is the only thing between the router and real
money, which is why 0.4 refuses a priced provider with no cap.

## Inputs needed from John

- The release of the Tau 0.14 port: its number and when. It breaks the config key,
  so rec: 0.2.0, with the shared ledger renumbered 0.3.0 and the later milestones
  moved up one. It needs your go before any tag.
- The starting model and pins. The router can't tell `-m`, `/model` before the
  first turn, and Tau's `default_model` apart:
  - `-m <a rung of the active profile>` isn't a pin, so the router starts from the
    top rung. `-m nemotron-super` (free) ran on claude-haiku-5-5 (paid) on
    2026-10-20.
  - A starting model outside the active profile *is* a pin. With
    `default_model: big` and `--ext-config tau_router.router:profile=free-only`,
    the run stayed on `big`, a paid model, and the profile was ignored
    (2026-10-21).
  - Rec: honour an explicit choice at its word. Then `-m` and `/model` pin, and
    `default_model` doesn't. This needs Tau to say where the model came from
    (#25).

- #28: the admission-hook design, which 1.0 hard caps need.
