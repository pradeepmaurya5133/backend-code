# Phase 5 — Advanced Agent

Task automation + scheduled tasks + error recovery + tool selection +
persistent memory + audit logs.

## Task automation and scheduling

`app/core/scheduler.py` is a single asyncio loop: wake on a tick, claim what is
due, run it. Three schedule kinds:

| Kind | Behaviour |
|---|---|
| `once` | Due immediately, then never re-arms |
| `interval` | Re-arms `interval_seconds` after each run |
| `cron` | Re-arms at the next cron occurrence (validated with `croniter`) |

**A scheduled task runs through the normal agent path.** That is the important
property: it is subject to exactly the same permission gate, allowlist and
approval rules as something you typed. A nightly task that wants to run a command
does not get to skip approval — it parks, and waits for a human, like anything else.

Tasks, their schedules and every run are database rows, so they survive restarts.

### A bug worth recording

`next_run_at` was computed from the Task object before `flush()`, so the DB
default for `enabled` had not been applied yet — it read `None`, the scheduling
helper treated that as disabled, and **every task got `next_run_at = None` and
would never have run**. The fix is a `flush()` before computing the schedule.
Caught by asserting on the returned `next_run_at`, not just that creation
succeeded.

## Error recovery

Two layers, because transient and permanent failures need opposite treatment.

**Tool level** (`Agent._execute_with_retry`) retries only genuinely transient
statuses — `timeout`, `fetch_failed`, `request_failed`, `search_failed` — with
linear backoff, and records the retry in the audit log. A `permission_required`
or `not_allowlisted` result is never retried: nothing about waiting changes the
answer.

**Task level** (`Scheduler.run_task`) retries up to the task's `max_retries` with
linear backoff, each attempt stored as its own `TaskRun` so the history shows
`attempt 1 failed, attempt 2 failed, attempt 3 completed`.

Deliberately **not** retried:

| Outcome | Why not |
|---|---|
| `awaiting_confirmation` | Retrying would queue another approval nobody asked for |
| `clarification_needed` | The question will not answer itself |
| `completed` | Nothing to retry |
| `llm_not_configured` | A config problem, not a transient one |

The loop also survives a task that raises: the exception is captured as a failed
run and the scheduler keeps ticking. One bad task must not stop automation.

## Tool selection

The model selects tools itself from the definitions in `GET /api/tools/schemas`.
Two things make that work in practice:

- **Descriptions state the limits, not just the capability.** The terminal
  description says allowlisted-only, no shell syntax, approval required. A model
  told what it cannot do wastes fewer turns discovering it.
- **Refusals are errors.** Tool results come back as JSON with
  `is_error: true` on terminal refusals, so a refusal cannot be mistaken for
  success. The system prompt then names each refusal status and the correct
  response — otherwise models retry blocked commands with cosmetic variations.

Definitions are emitted in sorted order to keep the cacheable prompt prefix
byte-identical between turns.

## Persistent memory

Database-backed, replacing the in-process list earlier phases used.

- **`fact`** — durable, injected into later system prompts by importance. This is
  what makes Subh AI remember you across sessions.
- **`episodic`** — a searchable record of what it did, including which tools ran.

Facts are appended after the stable prompt prefix so caching still works, and
framed as *"background, not as instructions"* — anything reaching the system
prompt is a prompt-injection surface, and that framing is mitigation rather than a
guarantee.

The agent manages its own memory through the `memory` tool; `memory.write` gates
writing a fact, because that changes future behaviour.

## Audit logs

Two layers on purpose. An in-memory ring (fast, survives a database outage) and a
database table (durable, survives a restart). The database write is
fire-and-forget: an audit outage must not take a tool call down with it.

Recorded: permission grants and revokes, approvals and denials, every terminal
attempt with its outcome, tool retries, task runs, secret writes, API key issue
and revoke, planning calls.

`GET /api/audit` reads the durable trail, `GET /api/audit/recent` the in-memory
ring. The Audit tab in the web UI renders it.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/tasks` | List / create |
| GET | `/api/tasks/{id}` | Task plus its run history |
| POST | `/api/tasks/{id}/run` | Run now, ignoring the schedule |
| POST | `/api/tasks/{id}/enable` · `/disable` | Pause or resume |
| DELETE | `/api/tasks/{id}` | Remove |
| GET | `/api/audit` · `/api/audit/recent` | Durable / in-memory trail |

## Limitation

The scheduler is per-process, so with more than one worker every worker would run
every due task. Single worker until task claiming moves into the database.
