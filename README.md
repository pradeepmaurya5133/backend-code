# Subh AI

A permission-controlled AI agent for web, mobile, tablet and desktop.

**The design principle:** the model never controls the operating system or an
external service directly. It *requests* an action from the tool orchestrator,
the permission layer decides whether that action is allowed, and only then does
the execution layer perform it. That's what makes "an AI that can do things"
stay controllable.

```
You ──► API ──► Agent ──► Planner (Claude) ──► Executor loop (Claude)
                                                      │
                                              requests an action
                                                      ▼
                             Tool Orchestrator ──► Permission Gate ──► Sandbox
                                                      │                   │
                                               allowed? denied?    allowlist + limits
                                                      ▼                   ▼
                                            Human Confirmation ──► Execution
                                                      │
                                              Audit ──┴──► Memory ──► You
```

## Phases

| Phase | Scope | State |
|---|---|---|
| 1 — AI Core | LLM, chat, memory, planning | Built; LLM unverified against the live API |
| 2 — Tools | Files, terminal, web, APIs | Built and running; web search needs a provider key |
| 3 — Voice | Speech → AI → Action → Speech | Built and running in browser mode |
| 4 — Application | React web, mobile, tablet, desktop | Web built and running; mobile/desktop written, not built |
| 5 — Advanced Agent | Automation, scheduling, error recovery, persistent memory, audit | Built and running |
| 6 — Production | Auth, encryption, permissions, Docker, deployment, monitoring | Built; Docker written but not run |

Per-phase detail is in `docs/`. **What is and isn't verified** is spelled out in
`docs/STATUS.md` — read that before trusting any of it in production.

## Quick start

```bash
# 1. Backend
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate       Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env                 # then set ANTHROPIC_API_KEY
uvicorn app.main:app --reload

# 2. Web client (separate terminal)
cd frontend/web
npm install
npm run dev
```

From the repository root, `npm run dev` and `npm run build` forward to
`frontend/web`, so either directory works.

- Web app: **http://localhost:5173**
- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/health

Without `ANTHROPIC_API_KEY` everything still runs: the UI loads, tools work, and
agent calls return `llm_not_configured` with an explanation rather than failing.

> Vite binds IPv6 `localhost`, so use `http://localhost:5173` — `127.0.0.1:5173`
> will not connect.

## Tests

```bash
cd backend && pytest -q        # 249 tests, no API key or network required
cd frontend/web && npm run build
```

LLM behaviour is tested against a scripted provider and persistence against
throwaway SQLite files, so the suite is hermetic.

## What Subh AI can do, and what stops it

Five tools, each gated. Nothing that reaches outside the sandbox, writes, or
deletes is on by default:

| Tool | Does | Default |
|---|---|---|
| `filesystem` | Read/write/delete inside one workspace directory | read only |
| `terminal` | Run allowlisted commands in a sandbox | **off** |
| `web` | Fetch a URL, search the web | fetch **off**, search on (needs a provider) |
| `http_api` | Call an allowlisted external REST API | **off**, and no hosts allowlisted |
| `memory` | Remember and recall across sessions | on |

Three independent gates stand between the model and a command running:

1. the `terminal.execute` permission is granted
2. the executable is on the allowlist, with no shell syntax
3. a human approved a token bound to **that exact command**

The model cannot approve its own work: `confirmation_token` is absent from the
tool schema it sees, and the server injects it only after an operator approves.
Credentials work the same way — the model names a stored secret and never sees
its value.

## Asking it to do something

```bash
# Grant the capability the request needs (off by default)
curl -X POST http://127.0.0.1:8000/api/permissions/grant \
  -H "Content-Type: application/json" -d '{"permission":"terminal.execute"}'

# Ask in plain language -> returns a plan plus a confirmation token
curl -X POST http://127.0.0.1:8000/api/agent/run \
  -H "Content-Type: application/json" \
  -d '{"message":"what python version do I have?","session_id":"demo"}'

# Approve what it proposed
curl -X POST http://127.0.0.1:8000/api/confirmations/approve \
  -H "Content-Type: application/json" -d '{"token":"<token>"}'

# Resume -> it runs and answers from the real output
curl -X POST http://127.0.0.1:8000/api/agent/resume \
  -H "Content-Type: application/json" -d '{"session_id":"demo"}'
```

The web UI does this for you: approvals appear as an Approve/Deny card in the
chat, showing the exact command before you decide.

## Before you deploy

`GET /api/preflight` lists every insecure default still in place, and the
**System** tab in the web UI shows the same list. In `ENVIRONMENT=production` the
app **refuses to start** while any critical one remains — a wrong `SECRET_KEY` or
`AUTH_ENABLED=false` in production is a failure, not a warning.

At minimum: set `SECRET_KEY`, `AUTH_ENABLED=true`, `DATA_ENCRYPTION_KEY`, and
point `DATABASE_URL` at PostgreSQL.

Run with **one worker** until the permission gate, confirmation store and
scheduler move into the database — they are per-process today, so two workers
would disagree about who approved what.

## Layout

```
backend/
  app/
    api/        HTTP routers
    core/       agent loop, planner, scheduler, runtime wiring, preflight
    db/         SQLAlchemy models, session, repositories
    llm/        provider abstraction (Claude + scripted/offline)
    security/   permissions, sandbox, confirmations, crypto, auth, audit
    services/   memory, secrets
    tools/      filesystem, terminal, web, http_api, memory
    voice/      pipeline + STT/TTS interfaces
  tests/        249 tests
frontend/
  shared/       API client used by every front end
  web/          React app (responsive: desktop, tablet, phone)
  mobile/       Expo / React Native
  desktop/      Tauri shell
docs/           per-phase documentation + STATUS.md
```

## Docs

- `docs/STATUS.md` — **what is verified and what isn't**
- `docs/ARCHITECTURE.md` — layering and the trust boundary
- `docs/PHASE_1_AI_CORE.md` — LLM, chat, memory, planning
- `docs/PHASE_2_TOOLS.md` — files, terminal, web, APIs
- `docs/PHASE_3_VOICE.md` — the speech loop
- `docs/PHASE_4_APPLICATION.md` — the clients
- `docs/PHASE_5_ADVANCED_AGENT.md` — automation and error recovery
- `docs/PHASE_6_PRODUCTION.md` — auth, encryption, deployment, monitoring
