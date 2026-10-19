# Design: router and planner extensions for Tau

Status: draft, 2026-10-15; revised 2026-10-17. This design builds on
`experiments/FINDINGS.md` (the evidence) and runs on Tau master (c759478), which
has the gap fixes and seeded `spawn_branch`.

## Goals

- **One model name in any session:** you set a *profile*, and the router keeps
  the conversation going across providers as budgets allow.
- **Optional, recursive planning:** a planner breaks a large prompt into tasks,
  or into sub-planners, and each one gets a slice of the budget.
- **Persistence from outside the model:** done-checks, resume policy, and caps
  per task. A model's own judgment never decides whether it is "done" or "good
  enough".

## Terms

- **Profile:** an ordered list of *rungs*, best first. Each rung is a model plus
  a reasoning level, so the model's own reasoning effort belongs to the rung,
  not to a separate knob.
- **Tier:** the highest rung a session or task may use, written
  `best-big@standard`.
- **Account:** a budget node. Accounts form a tree: persona → plan → task.
  Spending is charged to the account of the cursor that made the call.

## Layer 1: `router` (always loaded)

- **Ledger:**
  - every completion, priced with Tau's core `price_usage` (P3, which includes
    `cache_write`);
  - keyed by provider, account, cursor, and the (task kind, rung) pair;
  - holds come from `retry_after` and the response headers (P4).
- **Choosing a rung:** the best affordable rung at or below the tier. The router
  chooses at turn start, and again on budget events.
- **When it switches:** at the user-turn boundary by default. It switches in the
  middle of a loop (P6, `ctx.set_model` in `turn_end`) only when finishing on the
  current model would breach a hard cap. FINDINGS §3 shows that switching
  mid-task raised cost and lowered success.
- **What it shows other code:**
  - events `ext:router:spend`, `switched`, `budget_low`, `exhausted` and
    `refused`;
  - commands `/tier`, `/profile` and `/budget`;
  - the `budget_status` tool;
  - a way to open a child account for a cursor (used by the planner).
- **A profile as the model:** with no planner, a session whose model is a
  profile name is turned into a real model at every turn start.

## Layer 2: `planner` (only when asked: `/plan`, or a tool)

- **Plan nodes:** each node is a *planner* or a *leaf*, with:
  - a goal and its dependencies;
  - a tier and a budget slice;
  - a done-check;
  - a tool allowlist.
- **Running a plan:**
  - nodes run as `ctx.spawn_branch` sub-agents;
  - siblings without dependencies on each other run concurrently;
  - every node gets a child account from the router.
- **Recursion:**
  - a sub-planner splits its own slice and keeps a reserve;
  - a finished child's unspent budget and its results go back to its parent;
  - the next sequential sibling receives the leftover budget and the results
    before it;
  - parallel siblings share leftover only after they finish.
- **Who escalates: the parent, based on outcomes.**
  - A node that fails its done-check, or hits its cap, is retried one tier up
    (bounded), or handed back to its parent to re-plan.
  - A child may *ask* to escalate, but it never decides. E5 showed a small model
    keeping itself on a task it couldn't do.
- **Done-checks:**
  - tests, for code;
  - for research, travel or finance, a checklist or rubric that a model grades;
  - the planner writes each check together with its task.
- **Learning:** the success rate and $/task for each (task kind, rung) feed the
  planner's choice of tier.
- **Not automatic:** the router may suggest `/plan` someday, but not now.

## What `spawn_branch` provides (probed 2026-10-15, `experiments/ext/branch_probe.py`)

| question | answer |
|---|---|
| Do branch completions reach an extension's `message_end`? | **Yes**, with or without `hooks`. Each event carries the branch's `cursor_id` and the model it used, so spending can be charged to the branch's account. |
| Can branches run concurrently? | **Yes.** Two branches launched with `asyncio.gather` overlapped in time. |
| Can a branch spawn a branch? | **Yes, under two conditions.** (1) A child may only get tools its parent's turn offers, so tools narrow at each level just as the budget does; a sub-planner must be handed every tool its descendants will need. (2) A spawn from inside a tool call must be anchored at the leaf's *parent*. The leaf itself is the assistant message holding the unanswered call, so anchoring there produces Mistral's HTTP 400 "Not the same number of function calls and responses". |
| Do extension hooks run inside branches? | **Only with `hooks=True`.** Without it, `tool_call` and `turn_end` don't fire there, so the router can't enforce caps inside a branch. The planner should spawn with `hooks=True`. |
| Spawner → child cursor link | Available at spawn time: the spawner's `ctx.cursor.id`, then `BranchResult.cursor_id`. That is enough to build the account tree. |

The probe ran from a command in `-p` mode, and the session file then held only
the header, the config and the system prompt. Whether branch entries are
persisted in that path still needs checking.

## Where it lives

The repo is `tau-router`, which ships both extensions. The current catalog,
price, limit and hold modules become the router's library. The HTTP proxy is
deferred until a harness other than Tau needs it.

## Next steps

1. **Wait for the Tau feature branches** (P6, P1, P2, P3, P4, P5). Then rebuild
   `experiments/ext/governor.py` as `router`, removing the abort and
   host-resume workaround.
2. **Account tree in the router,** keyed by cursor id, with
   `open_account(cursor, slice, tier)` for the planner.
3. **A minimal planner:** one level, sequential, leftover passed forward, a
   done-check on every leaf. Test it on the E4 fixture against the E4/E5
   baselines.
4. **Then parallel siblings, then recursion.**

## Tau APIs as they land

**P4 (merged to Tau master, 2831a36)**

- **`message_end`:** the event's top-level `response_headers: dict[str, str] | None`.
  - Header names are lowercase. `None` means the headers weren't captured; `{}`
    means the server sent none.
  - Only the final `message_end` (the one carrying usage) has them, and they are
    never written to the session log.
- **`agent_end` and `provider_retry`:** `error_detail: ErrorDetail | None`
  (`tau_agent_core.events`).
  - Shape: `{type, status, retry_after, headers, retryable}`.
  - It is fully populated for `ProviderHttpError`, while a connection error
    gives only `type` and `retryable`.
  - Retried 429s show up on `provider_retry`.
- **How the router uses them:**
  - quota counters come from `message_end.response_headers`;
  - holds come from `provider_retry` / `agent_end` `.error_detail`;
  - the host's resume policy (`persona_host.recoverable`) can read `retryable`
    instead of scraping the error string.

**P3 + P5 (merged to Tau master, e6f62f3; f787814 renamed `enabled` to `auto`)**

- **`tau_agent_core.usage.price_usage(cost, usage) -> float | None`.**
  - It prices all four buckets, `cache_write` included.
  - `cost=None` returns `None`, meaning unpriced. A usage dict that has only the
    OpenAI key names raises.
  - The router prices with it instead of `governor.price`.
  - RPC still emits no cost.
- **Top-level config block `compaction`:** `{auto, reserve_tokens,
  keep_recent_tokens, summarizer}`.
  - Compaction is on by default (reserve 16384, keep 20000).
  - A per-model block replaces the top-level block; the two are not merged.
  - `summarizer` is a model name, resolved like any other model, so it needs no
    `api_key` of its own. Its context window must still be at least the session
    model's.
  - **For the persona:** set the summarizer to a free large-window model, such as
    `flash-lite` (1M) or `nemotron-super`, so a looping small model compacts
    instead of hitting a 400.

**P6 + P1 + P2 (merged to Tau master, 154a011; see Tau `docs/TURN-SETTINGS.md`)**

- **`ctx.set_model(name)` takes effect on the next request**, even inside the
  current loop.
  - It is recorded (`model_spec` plus `model=<name>`) right before that request,
    so `--continue` resumes on it.
  - On a branch cursor, it changes that cursor's frame.
  - The router switches models in `turn_end`, with no `abort`, followUp or host
    resume, and `chosen()` re-applying in `governor.py` goes away.
- **`ctx.set_reasoning(level)`:** `off|minimal|low|medium|high|xhigh`, effective
  on the next request and recorded as `thinking`.
  - **Not yet reliable across providers** (Tau issue #22). Until that is fixed,
    a rung's reasoning level comes from separate model entries (one config entry
    per model+thinking pair), not from `set_reasoning`.
  - There is no setter that resets reasoning to "unset".
- **`AbortSignal.reason`:** `"user"` or `"extension"`.
  - `ctx.abort()` is an extension abort; queued followUps then run on a fresh
    signal.
  - A user abort drops queued followUps and emits `follow_ups_dropped`.

## Workarounds and the Tau issues that remove them (0.13.0, filed 2026-10-18)

| workaround in `experiments/ext/` | Tau issue |
|---|---|
| `Router.__init__` reads `~/.tau/config.json` for the model catalog | #24 ctx model catalog |
| `on_input` infers a hand pick from `live id != last_set_id` | #25 turn-setting changes record their source |
| per-cursor dicts (`wanted`, `exhausted`, `last_model`), never cleaned up | #26 cursor_open/cursor_close for extensions |
| `on_refusal` skips a hold when `cursor_id` is None | #27 every agent_end carries cursor_id |
| a slice stops at `turn_end`, overshooting by up to one call | #28 pre-request admission hook |
| a handler exception is a stderr line, so enforcement stops silently | #29 (cites FINDINGS §7; keep that heading) |
| planner finds router via `ext:planner:need_router` | #30 docs: the event-plus-dict handshake |
| `/plan` is a prompt template, not a command | #31 docs: template plus tool |
