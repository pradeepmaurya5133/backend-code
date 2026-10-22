# Subh AI — web client

React + Vite. One responsive layout serves desktop, tablet and phone; the Tauri
desktop shell loads this same build.

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # dist/
```

Vite binds IPv6 `localhost`, so use **http://localhost:5173** — `127.0.0.1:5173`
will not connect.

## How it talks to the backend

`src/client.js` wraps `frontend/shared/api.js`, the same client the mobile and
desktop front ends use, so request shapes and error semantics stay identical.

- **Development:** `VITE_API_BASE` is unset, so calls go to this origin and
  Vite's `/api` proxy (`vite.config.js`) forwards them to
  `http://127.0.0.1:8000`. Same origin, so CORS never comes up.
- **Built and served separately** (the Docker image, Tauri): set
  `VITE_API_BASE` at build time, e.g.
  `VITE_API_BASE=http://localhost:8000 npm run build`. Vite inlines it, so it
  cannot be changed afterwards — and the origin you use must be listed in the
  backend's `CORS_ORIGINS`.

Start the backend first (`cd backend && uvicorn app.main:app --reload`). Without
it the header shows **API unreachable**.

## The tabs

| Tab | What it does |
|---|---|
| **Chat** | A turn, its plan, the tool calls it made — and the approval card when one is needed |
| **Tools** | Grant or revoke each permission; run a tool directly, through the same gates |
| **Automation** | Scheduled tasks: once, interval, or cron, with run-now and retries |
| **Memory** | Store and forget facts, and see exactly what gets injected into the system prompt |
| **Audit** | The durable trail: who asked for what, and what the gate decided |
| **System** | Health, metrics, the preflight report, and an optional API key / JWT |

## The approval card

When a turn needs human approval the server parks it and returns a token bound
to that exact call. The card shows the command verbatim before you decide, and
the client only ever sends approve/deny plus a resume — it never constructs a
token, and neither does the model.

A parked turn lives on the server, so reloading the page does not lose it: the
chat re-reads `/api/agent/pending` on mount and puts the card back.

## Voice

Browser mode, matching the backend's `VOICE_MODE=browser` default: the Web
Speech API does recognition and synthesis locally and only text crosses the
network, so no provider keys are needed. The **Speak** button appears only where
the API exists (Chrome and Edge; Firefox does not implement recognition).
