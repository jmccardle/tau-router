# Findings: an agent that knows its own costs (2026-10-14)

These are exploratory runs, a small number of each, all on small models. They
are meant to sharpen what to build, not to support statistical claims. Raw data
is in `out/`, which is gitignored.

Experiment spend, at list prices: Mistral $0.42, Anthropic $0.06,
Gemini $0.04 (free tier, so this is an upper bound), Cerebras $0.008, and NIM and
OpenRouter $0. Every provider stayed under $1.

## 1. What providers report, and how long caches live

`cache_probe.py` sent an 11–16k-token stable prefix plus a growing conversation,
with delays of 0, 2, 10, 30, 0, 90, 330, 0, 700 and 0 seconds before successive
turns. Models: Haiku 5.5, qwen-3.8-27b, gemini-3.5-flash-lite, mistral-small,
nemotron-3-super (NIM) and nemotron-3.5-lightning:free (OpenRouter).

| provider | cache signal in usage | warm after 90s | after 330s | after 700s | notes |
|---|---|---|---|---|---|
| Anthropic | `cache_read/creation_input_tokens`, explicit markers | yes | **cold** | cold | 5-minute TTL; each miss rewrites the whole prefix at 1.25× |
| Cerebras | `prompt_tokens_details.cached_tokens` | yes | yes | yes | caches in 128-token blocks (11264 of 11421) |
| Gemini | `cachedContentTokenCount` (implicit) | yes | **cold** | cold | covered only ~8.1k of 11.2k; the first call got no hit, a later run did |
| Mistral | `cached_tokens` | yes | **cold** | cold | |
| NIM | `cached_tokens` | yes | yes | yes | partial at first (9152), full later |
| OpenRouter free | `cached_tokens`, plus `usage.cost` | yes | yes | yes | the only provider that reports dollars itself |

Rate-limit headers: Anthropic sends `anthropic-ratelimit-*`, including token
reset times. Cerebras sends requests and tokens remaining per minute, hour and
day. Mistral sends `x-ratelimit-*`, including the token cost of the query.
Gemini, NIM and OpenRouter send none.

**For an agent:** waiting longer than 5 minutes between turns makes the next
Anthropic turn cost a full cache rewrite, while Cerebras, NIM and OpenRouter
stay warm. "Should I wait or act now" has a real price, and it differs by
provider. A model switch always starts with a cold cache.

## 2. What Tau gives an extension, verified by running it

- **Per-completion usage arrives on `message_end`** with all four buckets and
  `cache_reported`. Tau never fills `Usage.cost`, and Tau's own
  `compute_cost_usd` doesn't price `cache_write` (a real underbilling on
  Anthropic). `governor.py` prices all four buckets from the `cost` block in
  config.json.
- **Refusing a turn works:** the `input` hook returns `{"handled": True}`.
- **Choosing the model at turn start works:** `ctx.set_model` inside the
  `input` hook applies to that prompt.
- **There is no hook before each LLM request,** so a switch in the middle of a
  task needs `set_model` plus `abort`, and then a fresh submission.
  - **Tau gap:** a `followUp` queued before `abort` starts and then ends
    immediately. The aborted signal is reused for followUp re-entry
    (`agent_session.py:2875` resets it only once per submission).
    `persona_host.py` works around this by resuming the session with
    `--continue`.
- **Tau gap: `ctx.set_model` lasts only for the process.** `--continue`
  resumes on the session's recorded model. Before the governor re-applied the
  choice on every prompt, **the agent's `select_model` calls silently had no
  effect, and the agents then wrote reports crediting the wrong model**. In
  3 of 3 runs they confidently named ministral-3b when Haiku or mistral-small had
  done all the work.
- **Cross-provider history works.** Haiku's thinking blocks are replayed to
  Mistral as plain text, with a warning, and tool-call history converts fine.
  Moving into Gemini 3 in the middle of a tool loop is expected to fail
  (missing thought signatures), but I didn't test it.
- **Tau gap: compaction is off in every CLI head.** A small model that thrashes
  hits the 131k context limit and fails with a 400 (B-small-3).
- **`response_headers` (from the feature branch) never reaches extensions.**
  `message_end` drops it, so rate-limit headers still need a small core change
  to be visible to the governor.

## 3. Persistence: what a forced downgrade costs (E4)

The task: implement 7 functions until 28 checks pass. The fixture is
`fixtures/e4`, and a reference solution scores 28/28. A runs Haiku the whole
way. B runs ministral-3b the whole way. C and D start on Haiku, and the
governor forces ministral-3b after Haiku's **first** call (reading the files);
C passes a handoff note and D passes only "Continue the task."

| condition | passed all 28 | checks passed per run | spend per run |
|---|---|---|---|
| A: Haiku throughout | **5/5** | 28 ×5 | $0.0025–0.0033 (3–5 calls) |
| B: ministral-3b throughout | 2/5 | 14, 28, 9, 28, 0 | $0.0003–0.038 (4–158 calls) |
| C: downgrade + handoff note | 0/3 | 13, 24, 3 | $0.028–0.050 |
| D: downgrade, bare "continue" | 0/3 | 22, 26, 4 | $0.027–0.069 |
| C/D, downgrade after Haiku had already written the code | 4/4 | 28 ×4 | $0.002–0.003 |

1. **Cheap per token is not cheap per task.** ministral-3b costs 2.5× less per
   input token than Haiku. But on every attempt that kept working, it spent
   **4–23× more** than Haiku ($0.0125–0.069 against about $0.003), and it usually
   didn't finish. A rule like "downgrade when the budget runs low" *raises* spend
   on agentic work. Budgets should be judged on observed $/task (the idea behind
   Tau's `examples/53_router_ledger.py`), not on price per token.
2. **Switching models mid-task was the worst option measured.** Switching at a
   task boundary, or after the strong model had done the hard step, cost nothing
   extra.
3. **The handoff note made no measurable difference** (C vs D). The weak model's
   limits dominate. What it inherits matters more than what it's told.
4. **How the weak model fails**, each of which a persistent host has to handle
   from outside the model:
   - **Malformed tool-call JSON.** Tau rejects it, which is correct. Resuming
     helps, so `persona_host` now resumes on it, up to a limit.
   - **Context overflow** after a long thrash, because nothing compacts.
   - **Announcing a plan and ending its turn** without doing anything
     (B-small-5: 0/28 after 4 calls). Nothing re-prompted it, because the host
     only resumes after a governor switch.
   - **Endless edit/check loops:** 150–285 calls and 20-minute timeouts.
5. **"Determination" has to come from outside the model:** an external check of
   the goal (here, `check.py`), a resume policy, and a cap per task on calls or
   dollars that escalates or gives up rather than looping.

## 4. Can the agent choose its own model? (E5)

The setup: three tasks (arithmetic, the E4 coding task, a short poem) under a
$0.02 cap for the whole persona, with the `budget_status` and `select_model`
tools. Four runs after the governor fix:

- **Every run moved down to a cheaper model for the trivial task.** Each wrote
  a sensible reason, e.g. "Task 1 is one multiplication… cheapest model is
  enough".
- **In 2 of 4 runs the small model moved itself up for the coding task** (to
  Haiku and to mistral-small), then back down for the poem. Totals were
  $0.0036 and $0.0042, with all checks passing.
- **One run chose free NIM nemotron for everything,** which succeeded for
  $0.0013. That was the best outcome.
- **In one run ministral-3b kept itself on the coding task.** It took 76 calls
  and $0.020, hit the persona cap, and the governor forced it down to free
  nemotron, which finished. A small model judging whether it's "good enough" is
  the weak link.
- **All runs eventually passed 28/28.**

## 5. Candidate deliverables

1. **The governor as a Tau extension**, the core:
   - a per-provider ledger priced from Tau's `cost` blocks, `cache_write`
     included;
   - budget windows per provider and per persona;
   - refusing a turn at the `input` hook;
   - choosing a model at turn start;
   - a `budget_status` tool for the agent, and `select_model` with the choice
     enforced.
   
   Change compared with the prototype: **switch models at task boundaries
   rather than mid-task**, and when a budget crosses mid-task, finish on the
   current model up to a hard cap.
2. **A persona host** (now `persona_host.py`, later a `tau serve` client or a
   NATS-addressed workspace) that owns the goal, runs an external completion
   check, resumes after recoverable errors and early stops, and enforces caps
   per task. This is where "persisting" in both senses lives.
3. **Small Tau patches** (on a feature branch, for John's review):
   - persist `ctx.set_model` (via `append_config`);
   - let an extension restart the turn on a new model (reset the abort signal
     for followUp, or add an explicit `ctx.restart_turn(model=...)`);
   - price `cache_write` in `compute_cost_usd` and `ext_kit`;
   - put `response_headers` on `message_end`;
   - make compaction a configurable default in headless mode, with the cheap
     summarizer exposed in config.
4. **tau-router shrinks to a library** of catalog, prices, limits and holds,
   used by the governor. The HTTP proxy is optional, for harnesses other than
   Tau.

## 6. Open questions for John

- **Escalation authority:** should a small model be allowed to decide it's good
  enough, or should moving up or down be decided from observed $/task by the
  governor, with the agent only able to *ask*?
- **What counts as "done":** should goals always come with a check the host can
  run (tests, a file that must exist, a rubric graded by a model), so that
  persistence can be measured?
- **How should a persona experience its budget:** as numbers in a tool, as a
  standing system-prompt line, or only as refusals?

## 7. Checked by the Tau session (2026-10-15)

The `review-llm-response-headers` session confirmed all six gaps on ba54ca4. It
wrote seven fixture tests and all seven fail; gap 5 couldn't get a test, because
no config key exists to test.

- **Root cause: the agent loop reads its model and reasoning level once, at
  construction** (`agent_loop.py:839-847`), so a `ctx.set_model` call during a
  task only takes effect at the next `prompt()`.
  - Proposed fix (P6): the loop asks the session for the current model before
    each request, and Tau gains `ctx.set_reasoning`.
  - That makes the governor's abort, followUp and host-resume workaround
    unnecessary.
- **The other proposed fixes:**
  - P1: tag an abort with its source (user or extension).
  - P2: record the name of the chosen model so a resume finds it.
  - P3: one `price_usage` function in core that prices `cache_write`.
  - P4: `response_headers` on `message_end`, and a structured
    `error_detail.retryable` on `agent_end`.
  - P5: a `compaction` config block with an optional summarizer model.
- **Also found:** an exception raised in an extension handler becomes only a
  warning on stderr, and the turn carries on. A buggy governor would fail
  silently.

## 8. Router v0 on Tau master (1e28aaf), 2026-10-15

`ext/router.py` with `run_r1.sh`: the E3 six-file task. Haiku's budget is used up
after its first call, and the router switches to mistral-small **on the next
request of the same loop**. All six files were written in a single `tau -p`
process on one cursor, with no abort or host resume. Haiku's thinking replays
to Mistral as text, as before.

Response headers reach `message_end` for both providers. Anthropic sends
`anthropic-ratelimit-*` on streaming responses. **Mistral sends no
`x-ratelimit-*` on streaming responses**, although its non-streaming responses
in §1 had them. So quota counters for Mistral have to be tracked by the router
itself.

## 9. Planner prototype (2026-10-15)

`ext/planner.py` sits on top of `ext/router.py` and finds it through Tau's
pub/sub. The test is `fixtures/e6`: the E4 functions split across three
modules, each with its own check. Haiku plans, under a $0.05 cap for the whole
run.

| run | parts in parallel | first attempt | escalated (passed) | planner $ | total $ | result |
|---|---|---|---|---|---|---|
| p3 | 3 × ministral-3b | 1 of 3 passed | 2 → mistral-small (2 of 2) | 0.0060 | 0.0126 | ALL PASS |
| drive-smoke (discovered extensions) | 3 × ministral-3b | 1 of 3 passed | 2 → mistral-small (1 of 2) | 0.0060 | 0.0151 | ALL PASS, after the planner fixed the last part itself |

- **The design holds up end to end:** parallel children, budget slices per
  branch, a done-check on each child, escalation on failure, and the planner's
  own final check.
- **ministral-3b hit the 40-turn cap twice.** The cap and the check bound the
  thrashing that cost $0.03–0.07 per run in E4.
- **The planner is the largest single cost.** At this task size, delegating
  costs about 4× doing it directly with Haiku.
- **Tau issues found:**
  - `spawn_branch` frames children with the parent's API key, so a child on
    another provider gets HTTP 401. The fix is in progress in Tau; the router
    works around it.
  - A command in `-p` mode runs inside the turn lock, so `/plan` is an `input`
    rewrite rather than a command.
  - The router's `input` hook fires in branches spawned with `hooks=True`, so it
    must respect the planner's choice of model there.

## 10. Seeded branches and recursion (Tau `feat/seeded-spawn-branch`, bc23deb)

`start_child` now seeds each child the way John designed it. At the parent's
*assignment* (the user message for the top planner, or the `start_subagent`
result for a sub-agent), the child gets:

1. a `[router] Model switch` note;
2. a synthetic `start_subagent` call;
3. the brief, as that call's result.

The child then continues the agent turn. The session file confirms the shape:
user → config → note → `start_subagent` call → brief result → the child's own work.

- **p4 (one level):** ALL PASS for $0.0126. Mistral children ran under a Haiku
  parent with their own keys, which confirms the Tau key fix (d68156a).
- **p5 (recursion):** ALL PASS for $0.042.
  - Haiku handed the whole job to a single mistral-small sub-planner with a
    $0.04 slice.
  - That sub-planner opened three $0.01 accounts of its own, and one of those
    children opened a fourth level ($0.008).
  - **The nested accounts work.** The router stopped
    `root/make-check-pass` at $0.0401 of $0.04, counting all its descendants,
    and stopped each child at its own slice. Each overshot by at most one call,
    because the stop comes at `turn_end`, after the spend.
  - **The decompositions got sloppy deeper down.** A textutil sub-agent
    delegated a "durations" part. Depth costs money and coherence at this task
    size.
- **Gotcha:** a seeded tool result stores the tool's name as `tool_name`
  (snake_case), not `toolName`.
