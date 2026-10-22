# Status — what is verified, and what isn't

Written so nothing here reads as more finished than it is. The build environment
had no Anthropic credentials, no Docker, no PostgreSQL, no Android SDK and no
Rust toolchain, so some things could be exercised and some could only be written.

## Verified by running it

| Thing | How |
|---|---|
| 249 backend tests | `pytest -q`, no API key, no network |
| Agent loop, suspend/resume, parallel tool calls | Scripted LLM provider |
| Persistence across restarts | SQLite; suspended turns reload from the database |
| Terminal sandbox | Real subprocesses: 60s sleep killed at 3.2s, `curl` refused, pipes refused |
| Workspace containment | `../../../../etc/passwd` → `outside_workspace` |
| Web fetch | Real request to example.com; HTML reduced to text, script/style stripped |
| SSRF guards | `localhost`, `127.0.0.1`, `169.254.169.254`, private ranges all refused |
| DNS-before-allowlist ordering | Unlisted hosts are never resolved (exfiltration guard) |
| Scheduler | Ran live, 6+ ticks, cron/interval/once arithmetic, retries, non-retryable statuses |
| Encryption at rest | Fernet round-trip; tampered ciphertext → `None`; values never returned by the API |
| API keys & JWT | Issue, exchange, revoke, scope enforcement, forged/expired tokens rejected |
| Production refusal | `ENVIRONMENT=production` with default `SECRET_KEY` refuses to start |
| 48 HTTP endpoints | Live sweep against a running server |
| React web client | `npm run build` clean; dev server serving; `/api` proxy working |

## Verified with an invalid key

A placeholder key was put in `backend/.env` to exercise the real integration path,
then removed. This confirmed, against the actual `anthropic` SDK and the real
`api.anthropic.com` endpoint:

- `.env` is read and `build_provider()` switches from the unconfigured stand-in to
  `AnthropicProvider`
- `GET /api/agent/status` reports `configured: true`, model `claude-opus-5`
- `GET /api/preflight` drops its `ANTHROPIC_API_KEY` finding
- a real request is made and authenticated — it returned
  `401 authentication_error`
- that 401 maps to `LLMUnavailable` → agent status `llm_unavailable` at **HTTP
  200**, with the planner degrading to `planner_unavailable`, rather than a 500

So request construction, transport, auth headers, and the whole error-handling
path are exercised. Only model *behaviour* past authentication is still untested.

## Written but not executed here

| Thing | Why | What that means for you |
|---|---|---|
| **A Claude call with a *valid* key** | No `ANTHROPIC_API_KEY`, no `ant` profile on the machine | See "Verified with an invalid key" below — the integration path up to authentication *is* verified. What remains unverified is model behaviour: whether real plans parse, whether tool calls come back in the shape the loop expects, and whether a multi-turn tool conversation replays correctly. **Start with `{"plan": false}` on a read-only question** to isolate the executor from the planner. |
| Docker / compose | Docker not installed | Dockerfiles and compose are written to a reviewable standard but have never been built. Expect to iterate on the first `docker compose up`. |
| PostgreSQL | Not installed | Models are portable (`JSON`, no dialect-specific SQL) and run on SQLite. The Postgres path is unexercised; check it before trusting data to it. |
| Mobile client | No Android SDK / Xcode | Expo app and config complete, never built. |
| Desktop client | No Rust toolchain | Tauri config complete; it wraps the web build, which *is* verified. |
| Web search | Needs a provider key | `fetch` is fully real. `search` reports `provider_not_configured` until a key is stored; the integration point is there. |
| Server-side STT/TTS | No provider keys | Voice works end to end in **browser** mode (Web Speech API, no keys). The server-side interfaces exist with test doubles only. |

## Known limitations

- **Single worker only.** The permission gate, confirmation store and scheduler
  are per-process. Two workers would each have their own, so an approval granted
  on one would not be visible to the other. Conversations, memory, tasks and
  audit *are* in the database; those three are not, yet.
- **`create_all`, not migrations.** Schema changes will need Alembic before there
  is data worth keeping.
- **Approval endpoints are not rate-limited.** With `AUTH_ENABLED=false` anyone
  who can reach the API is a full admin, which is why production refuses to start
  that way.
- **Sandbox is policy, not OS isolation.** The allowlist, cwd pinning, timeout and
  scrubbed environment are enforced in Python — there are no job objects, cgroups
  or seccomp. A Python escape would not be contained by this layer alone.
- **No streaming.** Replies arrive whole, bounded by `LLM_MAX_TOKENS`.
- **Memory is a prompt-injection surface.** Stored facts enter the system prompt.
  They are framed as "background, not instructions", and web/file content is
  framed as data, but framing is mitigation, not a guarantee.
- **No cost controls.** Token usage is echoed per turn; nothing caps spend.

## One environment-specific change worth knowing

SQLAlchemy's compiled Cython extensions were blocked by a Windows Application
Control policy on the build machine. They were renamed to `*.pyd.blocked` inside
`backend/.venv` so SQLAlchemy falls back to the pure-Python modules it ships
alongside them — a supported configuration, just slower. **This only affects that
one virtualenv, not the repository.** A fresh `pip install` elsewhere will use
the compiled extensions normally.

## Suggested first steps

1. Set `ANTHROPIC_API_KEY`, restart, and check `GET /api/agent/status` reports
   `configured: true`.
2. Ask something read-only: *"list the files in my workspace"*. That exercises
   planner → executor → tool → result → answer without any approval.
3. Grant `terminal.execute` and ask for the Python version. You should get an
   approval card; approve it and confirm the real output comes back.
4. Read `GET /api/preflight` and work through it before exposing the API.
