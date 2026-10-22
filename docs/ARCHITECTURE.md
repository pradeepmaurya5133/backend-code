# Architecture

**The model never controls the operating system or an external service directly.**
It requests an action from the tool orchestrator, the permission layer decides
whether that action is allowed, and only then does the execution layer perform it.

```
Client (web / mobile / tablet / desktop)
   │
   ▼
FastAPI  ──►  Agent  ──►  Planner (Claude, no tools)
                 │              └─► structured plan, or a clarifying question
                 ▼
          Executor loop (Claude)
                 │  "I want to run `python --version`"
                 ▼
        Tool Orchestrator (registry)
                 │
                 ▼
          Permission Gate ──── denied ──► permission_required  ─┐
                 │ allowed                                      │
                 ▼                                              │
             Sandbox ─────── not allowlisted ──► refused  ───────┤
                 │ allowlisted                                  │
                 ▼                                              │
        Human Confirmation ── denied ──► token_denied  ──────────┤
                 │ approved                                     │
                 ▼                                              │
           Execution Layer                                      │
                 │                                              │
                 ▼                                              ▼
              Audit  ◄─────────────────────────────────── every decision
                 │
                 ▼
           Memory ──► Agent ──► Client
```

Each refusal returns to the model as a `tool_result` flagged `is_error`, so it
learns the action did not happen rather than assuming success.

## The trust boundary

The model is treated as an **untrusted planner**, not a privileged operator:

- It *proposes* tool calls; the gates decide whether they run.
- It cannot see or mint a confirmation token — `confirmation_token` is absent from
  the tool schema it receives, and the server injects it only after a human
  approves. It cannot approve its own command.
- It cannot supply credentials. `Authorization`/`Cookie` headers it sets are
  stripped; it names a stored secret and the server substitutes the value.
- Refused results reach it flagged as errors, so a refusal cannot read as success.
- Content it reads — web pages, files, memory — is framed as **data, not
  instructions**, and the system prompt tells it to report embedded directions
  rather than follow them.

## Two LLM stages

**Planner** turns the request into a structured, inspectable plan and is given
**no tools**, so planning cannot execute anything. **Executor** runs the tool-use
loop, choosing tools turn by turn because tool output routinely changes what the
next step should be. The plan is intent; the loop is what actually happens.

## Layers

| Layer | Package | Responsibility |
|---|---|---|
| Transport | `app/api/` | HTTP, validation, scope checks |
| Orchestration | `app/core/` | Agent loop, planner, scheduler, runtime wiring, preflight |
| Model | `app/llm/` | Provider abstraction (Claude, scripted) |
| Policy | `app/security/` | Permissions, sandbox, confirmations, crypto, auth, audit |
| Capability | `app/tools/` | filesystem, terminal, web, http_api, memory |
| Services | `app/services/` | Memory, secrets |
| Persistence | `app/db/` | Models, session, repositories |

Dependencies point inward: tools depend on policy, never on transport. A tool has
no idea whether it was invoked by the model, by `POST /api/tools/execute`, or by
the scheduler — which is exactly why all three are equally gated.

## One security context

`app/core/runtime.py` constructs a single `PermissionGate`, `WorkspacePolicy`,
`ConfirmationStore`, `AuditLog`, `ConversationService`, `SecretService` and
`ToolRegistry` for the process. Before this existed each router built its own
gate, so a grant made through one API had no effect on another — a real bug, not a
hypothetical one.

Enforcement lives in the **tools**, not the agent loop. Each tool checks the
specific permission its requested operation needs (`filesystem.write`,
`terminal.execute`, `api.write`), so the agent must not pre-filter on a coarse
tool name.

## Persistence

| Durable (database) | Per-process (not yet) |
|---|---|
| Conversations and messages | Permission gate |
| Suspended turns (parked approvals) | Confirmation store |
| Memory (facts and episodic) | Scheduler claims |
| Tasks and task runs | |
| Audit trail | |
| API keys, encrypted secrets | |

That right-hand column is why the app must run with **one worker**. Suspended
turns are in the database, so a resume survives a restart; but two workers would
disagree about which permissions are granted and both would run every due task.

SQLite by default (zero setup), PostgreSQL in deployment — same models, portable
`JSON` columns, no dialect-specific SQL.

## Platform adapters

Device-specific capability belongs behind an adapter, so one agent API serves
every client.

**Implemented:** filesystem workspace, terminal sandbox, web/HTTP, Claude
provider, browser voice.

**Interfaces defined, no provider wired:** server-side speech-to-text,
text-to-speech, web search.

**Future:** browser automation, notifications, camera/microphone.
