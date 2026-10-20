# Roadmap

## What tau-router is (decided 2026-10-18)

tau-router is a **Tau extension package**: the `router` and `planner` extensions, plus
a small library they import for prices, the catalog, the ledger and budget periods.
Several Tau processes can run at once against the same accounts, so all shared state
lives in one ledger that every instance reads and writes.

The HTTP proxy that the 0.0.1 core was built toward is not part of 1.0 (see "Not in
1.0").

## Status (2026-10-18)

- **Version:** 0.1.0, tagged `v0.1.0` and published to PyPI as `ffwf-tau-router`
  (the import stays `tau_router`). `/plan` is linked in by hand until john/tau #39
  lands. The session's TUI drive of the status strip served as the 0.1 check; John's
  own drive is the 1.0 sign-off.
- **Next:** 0.2, the shared SQLite ledger. Nothing blocks starting it.
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

### With Tau 0.14.0: module names everywhere

John decided the #35 spelling on 2026-10-18: colons delimit structure, and dots
belong to module names. Every site spells the full module name with its dots, and
nothing turns `.` into `_`. A short name such as `planner` works only where a person
types it interactively, is resolved fresh each time, and is refused when ambiguous.
Stored config always uses the full module name. This lands in the tau-router
release that requires `ffwf-tau-agent-core>=0.14.0`, and never ahead of Tau 0.14.0,
because on 0.13 these names don't resolve.

| site | 0.13 (now) | with 0.14 |
|---|---|---|
| planner finds the router | `api.on("ext:planner:need_router")` (router.py:495) | `api.on("ext:tau_router.planner:need_router")`. planner.py:101 is unchanged: Tau prefixes the emitter's module name |
| config | `extensions.router`, `extensions.planner` | `extensions."tau_router.router"`, `extensions."tau_router.planner"` |
| `--ext-config` | `router.profile="p"` (split on the first `.`) | `tau_router.router:profile="p"` (split on the first `:`) |
| command owners | `ext:router.budget` | `ext:tau_router.router:budget`; typing `/budget` still works |
| loading | `tau $(tau-router ext-args)`, through the thin files in `tau_router/ext/` | entry points `tau.extensions`, authorized once per installed version |

The change list:
- `router.py`: the subscription topic, the docstring config path, and the
  ext:<them>:need_router comment.
- `planner.py`: the docstring, and the not-loaded error, which names
  `tau_router.router`.
- `tests/conftest.py`: `FakeApi.emit` publishes as `ext:tau_router.planner:<topic>`,
  and `load_router` looks up that topic. Tests import `tau_router.router` and
  `tau_router.planner` directly.
- README, `TEST-DRIVE.md`, `make_tau_home.py`, `run_plan.sh` and
  `run_plan_nested.sh`: the config keys and `--ext-config` spelling. The archived
  experiment scripts stay as they ran.
- `tau_router/ext/`, `cli.py ext-args` and `test_package.py`'s `ext-args` test:
  remove them, unless Tau 0.14's `-e` path loading still needs them (check against
  the 0.14 build). `tau-router prompt-dir` stays until #39.
- `pyproject.toml`: drop the "provisional" note on the `tau.extensions` group once
  0.14 fixes the name.
- README install: authorizing the tau-router version (#35), and re-authorizing
  after an upgrade.
- README upgrade note, stated plainly: a config still under the old
  `extensions.router` key leaves the router unconfigured, so it fails to load.
  Tau shows a notice and keeps running, which means **no budget is enforced**.
  A user who needs the guarantee loads the router with `-e tau_router.router`,
  so that a load failure stops the run.

Built in Tau on `feat/ext-packages` @ 55a0028 (awaiting John's review). What the
build adds to the plan above:
- The old `--ext-config router.KEY=...` form fails at startup, so the run scripts
  and docs change in the same commit as the dependency bump.
- Entry points must name a module (`module:attr` is unusable), under the group
  `tau.extensions`. tau-router's already do.
- Installed packages need `tau ext authorize tau_router.router` (and
  `tau_router.planner`). Headless and serve modes don't prompt: they print one
  line and run without the extension. So `make_tau_home.py` authorizes both in
  the sandbox HOME, and the README install says to authorize, and to authorize
  again after an upgrade. Because the planner refuses loudly when the router is
  missing, an unauthorized router shows up as that error, not as silent
  unbudgeted spending.
- `--tools` becomes an allowlist over every tool. A run that passes `--tools`
  must name `delegate`, `budget_status` and (in agent mode) `select_model`, or the
  extensions lose them. No tau-router script passes `--tools` today; the README
  says so.

- Persistent router states through `api.set_warning` (Tau #60): budget exhausted
  (`error`), a provider's allowance below its reserve (`warning`), and a pin that
  overrides the profile. They show in the TUI footer and `/extensions`, and reach a
  client that attaches later; the router clears each when it no longer holds.
  Call `api.set_warning` and `ctx.ui.*` only from Tau's event loop (john/tau #64 will
  refuse an off-loop call); the router's hooks and planner branches already run there.
  Warnings persist across `/new`, fork and switch: right for provider allowances, wrong
  for a session budget, so the router clears its session-scoped keys on session start
  and switch.

- A rung whose model entry Tau can't build (#65; John chose option (c): only the
  selected entry is fatal at startup, every other bad entry is a startup warning, so a
  bad entry can sit in a profile) is refused by `ctx.set_model` before any request. The router catches Tau core's `ModelUnavailableError` (proposed
  on fix/home-and-model-followups; until it lands, `ValueError`) and `KeyError` (a name
  not in config), marks that rung blocked with the reason in `/budget`, and steps to
  the next rung instead of failing the turn. It never imports `tau_coding_agent`.
  The router keeps reading `config.json` for its catalog until #24 gives extensions
  one (planned for Tau 0.15).
  **Required in the 0.14 release, with a test:** live on Tau f81e361, an uncaught
  `ModelUnavailableError` from the router's `input` hook was logged as an extension
  error, and the turn then ran on the over-budget rung, bypassing the cap (Tau #29
  covers the Tau side). 0.1.0 can't hit it, because it's capped below Tau 0.14.

- A 401 or 403 blocks the rung persistently. The reason comes from the error's
  `key_sent` field (Tau fix/69-keyless): False gives "no API key", True gives "API key
  refused", None (a third-party provider) gives "HTTP 401". It never parses hint text.
  The router holds only on 429/503/529 today, and from Tau 0.14 (#69) a keyless model
  sends its request and gets the provider's real 401 on every turn. A 401 isn't
  retried, so it arrives on the final error (`agent_end`), not on `provider_retry`.

Check with Tau 0.14:
- A live run of the e6 plan fixture and a TUI drive on the 0.14 build, from an
  installed, authorized package. None has been done against tau-router yet.
- #44: a subscription to an emitter that isn't loaded is flagged. Loading both
  extensions must flag nothing for `need_router`, and loading the router alone
  should flag it.
- #42: Tau 0.14 creates the session at mount, so `/budget` completes on the
  startup screen. Re-check in the TUI.

### 0.2.0 One shared ledger

- Paint the status strip on `session_start`. With Tau 0.14 creating the TUI session at
  mount (#42), the strip is visibly blank until the first input, because the router
  sets it only from `input`, `message_end` and `turn_end`.
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
| 0.1 (TUI) | #42 the startup screen has no session, so the editor's hint says `/budget` and the other extension commands "go to the model as text", and completion lists none of them. Sending one still runs it: `AgentSession.submit` checks again once the session exists (verified on 0.13.0) | decided: the session is created at mount, in Tau 0.14.0 |
| Tau 0.14 | #35 build: one spelling for dotted module identifiers in `--ext-config`, config keys, `ext:<name>:<topic>` and command owners | decided 2026-10-18: full dotted module names, `:` as the delimiter. tau-router's rename is planned in "With Tau 0.14.0" and lands with it |
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

- `-m <model>` naming a rung of the active profile isn't a pin: the router starts
  from the top rung, so `-m nemotron-super` (free) ran on claude-haiku-5-5 (paid) on
  2026-10-20. Should `-m` pin, like `/model`, or set the tier to that rung? Rec: pin.

- #28: the admission-hook design, which 1.0 hard caps need.
