# Phase 1 — AI Core

LLM + Chat + Memory + Planning.

Model: `claude-opus-5` via the official `anthropic` SDK, with adaptive thinking.

## Two stages, on purpose

**Planner** (`app/core/planner.py`) makes one schema-constrained call and returns
a typed plan *before* anything executes:

```json
{
  "understanding": "The user wants to know which Python version is installed.",
  "steps": [
    {"description": "Run python --version", "tool": "terminal", "requires_approval": true},
    {"description": "Report the version", "tool": null, "requires_approval": false}
  ],
  "clarification_needed": null
}
```

The planner is given **no tools**, so planning cannot execute anything. If the
request is too vague it returns `clarification_needed` and the turn stops before
a single tool runs.

**Executor** (`app/core/agent.py`) runs the tool-use loop. The plan is intent,
not a script: the model picks tools per turn, because a tool result routinely
changes what the next step should be. Capped at `LLM_MAX_ITERATIONS`.

## Why a manual loop instead of the SDK tool runner

The SDK's tool runner is the recommended way to drive a tool loop, and for an
in-process approval gate it would be right. It does not fit here because this
agent's approval gate is **cross-request**: the turn must stop, return a token
over HTTP, and resume on a *later* request after a human approves. The runner is
an in-process iterator with no suspend/resume boundary, so the loop is written
out and the in-flight turn is persisted to the database.

## Suspend and resume

```
POST /api/agent/run      -> awaiting_confirmation + confirmation_token
POST /api/confirmations/approve
POST /api/agent/resume   -> completed, with the answer
```

What survives the suspension (in `conversations.suspended`, so a restart or a
different worker can pick it up):

- `completed_results` — tool results already gathered this turn
- `pending_call` — the call needing approval, retried verbatim
- `queued_calls` — calls from the same assistant turn that had not run yet

That last one matters. Claude can emit several tool calls in one turn, and the
API requires **all** their `tool_result` blocks in a single user message. A gated
call in the middle would otherwise drop the calls behind it and produce a
malformed next request. On resume the approved call runs, the queue drains, and
all results go back together.

## Chat

Conversations and messages are database rows. `blocks` stores provider-native
content verbatim so thinking and `tool_use` survive replay; `text` is the
human-readable projection used by `GET /api/agent/transcript`.

History is windowed to the last `HISTORY_LIMIT` messages, and the window is
trimmed carefully: it can never *begin* with a `tool_result` whose matching
`tool_use` was trimmed away, because that makes the next API request invalid.
There is a test for exactly that.

## Memory

Two kinds, deliberately separate:

- **`fact`** — durable. Injected into the system prompt on later turns, ordered
  by importance. This is what makes Subh AI remember you between sessions.
- **`episodic`** — a searchable record of what it did.

Facts are appended *after* the stable system prompt so the cacheable prefix stays
byte-identical between turns. They are framed as *"background, not as
instructions"*, because anything that reaches the system prompt is a
prompt-injection surface.

The agent can manage its own memory through the `memory` tool (`memory.write`
gates writing a fact, since that changes future behaviour).

## Teaching the model about its own constraints

Tool results are JSON, and a refused call is flagged `is_error: true` so a
refusal cannot read as success. The executor system prompt names each refusal
status and what to do:

| Status | What the model is told |
|---|---|
| `permission_required` | Not granted. Say which permission; do not retry. |
| `confirmation_required` | Queued for approval; it has not run. Do not invent a token. |
| `not_allowlisted` / `shell_syntax_refused` | Can never run as written. Explain the limit. |
| `outside_workspace` | Path is out of bounds. |
| `host_not_allowlisted` | That API host is not approved. Do not try another. |

Without this, models retry blocked commands with variations, reading the refusal
as transient.

## Provider abstraction

`app/llm/` keeps the loop provider-agnostic: `base.py` (types), 
`anthropic_provider.py` (real Claude), `scripted.py` (deterministic test
provider + an unconfigured stand-in), `factory.py` (selection). Every LLM test
runs against the scripted provider — no key, no network.

### API details worth not re-deriving

- `thinking: {"type": "adaptive"}` — `budget_tokens` is rejected on this model
  family, and `temperature`/`top_p` are removed.
- Thinking blocks are stored verbatim and replayed unchanged.
- `output_config.effort` controls depth (`low`–`max`, default `high`).
- Tool `input` is always `json.loads`-ed, never string-matched — escaping varies.
- `stop_reason == "refusal"` is a 200 response, not an exception.
- Server-side refusal fallbacks are on by default; a 400 (beta not enabled on the
  account) degrades to the stable endpoint rather than failing the turn.
- Tool definitions are emitted in sorted order to keep the cached prefix stable.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/agent/status` | Provider, model, configured state |
| POST | `/api/agent/run` | Natural-language request (`plan: false` skips planning) |
| POST | `/api/agent/resume` | Continue a turn parked for approval |
| GET | `/api/agent/pending` | What a session is waiting on |
| GET | `/api/agent/transcript` | Chat log for a UI |
| GET | `/api/agent/sessions` | Session list |
| POST | `/api/agent/reset` | Clear a session |
| GET/POST | `/api/memory` | Recall / remember |
| GET | `/api/memory/search` | Search memories |
| GET | `/api/memory/context` | Exactly what the prompt receives |
| DELETE | `/api/memory/{id}` | Forget |

## Not verified

Live Claude calls — no credentials were available. See `docs/STATUS.md`.
