# Phase 6 — Production

Authentication + encryption + permissions + Docker + cloud deployment + monitoring.

## The honest starting point

Every default in this project is tuned for *development*, which is the wrong
setting for a deployment. Rather than hoping someone reads a checklist,
`app/core/preflight.py` enumerates the insecure defaults, serves them at
`GET /api/preflight`, shows them in the web UI's System tab — and in
`ENVIRONMENT=production` **refuses to start** while any critical one remains.

Verified: with the default `SECRET_KEY`, production startup raises
`InsecureConfiguration` and names each problem with its fix. Silently running
with `SECRET_KEY=change-me` is worse than failing to boot.

| Finding | Severity | Why |
|---|---|---|
| `SECRET_KEY` default or < 32 bytes | critical / high | Signs JWTs and keys API-key hashes |
| `AUTH_ENABLED=false` | critical | Every caller becomes a full admin |
| `DATA_ENCRYPTION_KEY` unset | high | Secrets keyed off `SECRET_KEY`; rotating it orphans them |
| `DATABASE_URL` is SQLite | medium | No concurrent writers, no second worker |
| `CORS_ORIGINS` contains `*` | high | Any site could call the API with credentials |
| `ANTHROPIC_API_KEY` unset | medium | Agent calls return `llm_not_configured` |

## Authentication

Two credential types, one principal model.

- **API keys** (`X-API-Key`) for scripts and CI. Generated as
  `subh_` + 32 random bytes, returned **once**, and only a keyed HMAC-SHA256 hash
  is stored — so a leaked database cannot be brute-forced offline without the
  server secret.
- **JWT** (`Authorization: Bearer`) for browser clients, obtained by exchanging an
  API key at `POST /api/auth/token`.

Scopes are coarse by design, because the fine-grained decisions are the
permission gate's job: `read`, `agent:run`, `confirmations:approve`, `admin`
(which implies the rest).

Disabled by default so local development needs no setup. With it off every caller
is `local-operator` holding all scopes — and `/api/health` and `/api/auth/status`
say so plainly, so an exposed deployment is obvious rather than silent.

`/api/health`, `/api/ready` and `/api/auth/status` stay public so probes and
login flows keep working with auth on. Everything else requires a scope.

## Encryption at rest

Third-party credentials are encrypted with Fernet — AES-128-CBC plus an HMAC, so
a tampered ciphertext fails to decrypt rather than decrypting to garbage. Tested:
round-trip, tamper-rejection, wrong-key rejection, and that the same plaintext
encrypts differently each time (random IV, so identical secrets are not
correlatable).

**Values are never returned by the API.** `GET /api/secrets` lists names only.
The only read path is `SecretService.reveal()`, used server-side by the
`http_api` tool to inject a credential into an outbound request — so a key can be
*used* without ever entering the model's context or an API response. Verified
live: a stored value does not appear in any response.

`DATA_ENCRYPTION_KEY` should be a dedicated Fernet key. Left blank it is derived
from `SECRET_KEY` via PBKDF2, which works but means rotating `SECRET_KEY` orphans
every stored secret — so that derivation is flagged in both the preflight report
and the API response (`key_derived_from_secret_key: true`).

## Permissions

Phase 2 covers the model. Phase 6 adds the operator surface: list, grant, revoke
and reset to defaults, all `admin`-scoped and all audited. Only permissions a
registered tool actually declares can be toggled, so a typo cannot create a
permission nothing will ever check.

## Docker

`backend/Dockerfile` is multi-stage: a builder with the toolchain, a slim runtime
with only the virtualenv. It runs as **non-root uid 10001** — the terminal tool
spawns subprocesses, and if that sandbox is ever bypassed the blast radius should
not include root. `git` is installed because it is on the sandbox allowlist. There
is a `HEALTHCHECK` against `/api/health`.

`frontend/web/Dockerfile` builds the React app and serves it from nginx with
immutable caching on hashed assets, `no-store` on `index.html` (so clients cannot
pin to a stale bundle), and `nosniff` / `DENY` / `strict-origin-when-cross-origin`
headers. Its build context is `frontend/` rather than `frontend/web/`, because the
app imports the shared client from `../shared`.

`docker-compose.yml` wires api + web + Postgres, with the API waiting on a
Postgres `healthcheck` so it does not race the database on first boot, and the
agent workspace on a named volume so files it writes survive restarts.

**Not built or run: Docker is not installed in this environment.** These files are
written to a reviewable standard but unexercised — expect to iterate on the first
`docker compose up`.

## Monitoring

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Liveness. Public. Names the agent, environment, whether auth and the LLM are configured |
| `GET /api/ready` | Readiness. Actually queries the database; returns **503** if it cannot |
| `GET /api/metrics` | Uptime, model, scheduler state and tick count, permission snapshot, audit counts, pending approvals, session and key counts |
| `GET /api/preflight` | Outstanding insecure defaults |
| `GET /api/audit` | Durable audit trail |

`/health` and `/ready` are separate on purpose: a liveness probe that queries the
database restarts a healthy container during a brief database blip.

Metrics are JSON rather than Prometheus text. A `/metrics` exporter would be the
next step if you are scraping.

## Deployment checklist

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"                      # SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # DATA_ENCRYPTION_KEY
```

1. Set `SECRET_KEY`, `DATA_ENCRYPTION_KEY`, `AUTH_ENABLED=true`, `ENVIRONMENT=production`.
2. Point `DATABASE_URL` at PostgreSQL.
3. List real origins in `CORS_ORIGINS` — never `*`.
4. Set `ANTHROPIC_API_KEY`.
5. Issue an admin API key, then verify `GET /api/preflight` is clean.
6. Terminate TLS at a reverse proxy; nothing here serves HTTPS.
7. Keep **one worker** (see below).
8. Replace `create_all` with Alembic migrations before the data matters.

## Known gaps

- **One worker only.** The permission gate, confirmation store and scheduler are
  per-process. Two workers would disagree about who approved what, and both would
  run every scheduled task.
- **No rate limiting** on authentication or approval endpoints.
- **No secret rotation flow** — re-encrypting under a new key is manual.
- **The sandbox is policy, not OS isolation.** No job objects, cgroups or seccomp.
- **No cost controls.** Token usage is reported per turn; nothing caps spend.
