# Phase 2 — Tools

Files + Terminal + Web + APIs. Plus memory, which Phase 1 describes.

Every tool follows the same contract: it returns a JSON dict with a `status`, it
checks its own permission against the shared gate, and it never raises into the
agent loop. A tool that cannot do something says so; it does not throw.

## The permission model

Fine-grained, dotted, and fail-closed — an unknown permission is denied, so a
typo cannot accidentally open a capability.

| Permission | Default | Why |
|---|---|---|
| `filesystem.read` | on | Read-only, inside one directory |
| `filesystem.write` | **off** | Mutates |
| `filesystem.delete` | **off** | Destroys |
| `terminal.read` | on | Only lists the allowlist |
| `terminal.execute` | **off** | Runs code |
| `web.search` | on | No provider configured anyway |
| `web.fetch` | **off** | Reaches the network |
| `api.call` | **off** | Reaches approved external services |
| `api.write` | **off** | Mutates remote state |
| `memory.read` | on | Local, harmless |
| `memory.write` | on | Useful; facts are framed as data |

## filesystem

Everything resolves against one workspace root. `WorkspacePolicy.resolve()`
resolves the path and *then* verifies it is still under the root, so `..`
traversal and symlink tricks both land outside and are refused with
`outside_workspace`.

Deliberately limited: no recursive delete (a non-empty directory returns
`directory_not_empty`), the workspace root itself cannot be deleted, and
non-UTF-8 files are reported rather than mangled. Paths come back
workspace-relative, so the host layout is never disclosed.

## terminal

**The allowlist is the whole point.** An earlier iteration used a blocklist,
which fails open — anything unnamed was treated as safe, so `curl`,
`powershell`, `certutil` or any renamed binary walked straight through. An
allowlist fails closed.

Three independent gates, each checked before the next:

| # | Gate | Refusal |
|---|---|---|
| 1 | `terminal.execute` granted | `permission_required` |
| 2 | Executable allowlisted, no shell syntax | `not_allowlisted`, `shell_syntax_refused` |
| 3 | Human approved *this exact* command | `confirmation_required`, `token_denied` |

Sandbox properties (`app/security/sandbox.py`):

- **No shell.** `shell=False` with an argv-split command, so metacharacters are
  never interpreted. Bare pipe, ampersand, semicolon, redirect, backtick and
  `$(` are refused; the same characters *inside a quoted argument* are inert
  literals and allowed — checking the raw string instead would reject
  `python -c "a; b"` for no reason.
- **Workspace cwd.** Verified live: the process reports the workspace, not the repo.
- **Timeout.** 15s default, 120s ceiling. Verified: a 60s sleep died at 3.2s.
- **Output ceiling.** 20k chars, with `truncated: true`.
- **Scrubbed environment.** Only `PATH`, `SYSTEMROOT`, `TEMP` and similar pass
  through, so `SECRET_KEY` and API keys are not inherited by subprocesses.

### Token rules

- **Bound to one command.** A mismatched call is refused *without consuming the
  token*, so a wrong attempt cannot invalidate a legitimate approval. This was a
  real bug found by live testing, not theory.
- **Single use.** A consumed token cannot be replayed.
- **Expiring.** Five minutes.
- **Revocable mid-flight.** Revoking the permission after approval still blocks
  execution; gate 1 is re-checked on every call.

## web

`fetch` is a real HTTP GET. The guards matter more than the feature:

- **SSRF.** Loopback, private, link-local, reserved and multicast addresses are
  refused — including the cloud metadata endpoint `169.254.169.254`.
- **DNS rebinding.** The check runs *after* resolution, so a public hostname
  pointing at `127.0.0.1` is still refused.
- **Non-blocking resolution.** `getaddrinfo` runs in a worker thread; calling it
  directly would stall the event loop for the whole lookup.
- **Scheme allowlist.** Only `http`/`https`; `file:`, `data:` and `javascript:`
  are refused by name.
- **Content reduction.** HTML is stripped to readable text with `script` and
  `style` contents removed, so the model never reads page JavaScript.
- **Caps.** A byte cap on download and a character cap on text, both flagged.

`search` needs a provider key. It is deliberately a **client-side** call rather
than the model's own server-side web-search tool, because a server-side tool
would bypass this project's permission layer entirely. Until a key is stored it
reports `provider_not_configured`.

## http_api

The widest-reaching capability, so the most restricted:

- **Host allowlist.** Empty means nothing is reachable — the capability is off
  until an operator opts a host in. An entry covers subdomains, but
  `example.com` does **not** authorise `notexample.com`.
- **The allowlist is checked before DNS.** Resolving an unapproved host would
  leak data to its nameserver even when the request is refused — a usable
  exfiltration channel. There is a regression test asserting no lookup happens.
- **Internal addresses refused even when allowlisted**, so an entry cannot
  become a route to internal services.
- **Credentials never come from the model.** `Authorization`, `Cookie` and
  `Proxy-Authorization` headers it sets are stripped. To authenticate, it sets
  `auth_secret` to the *name* of a stored secret and the server substitutes the
  value, so a key never enters the transcript.
- **Writes need a second permission.** `api.call` allows GET/HEAD; anything that
  mutates also needs `api.write`.

## Driving tools directly

`POST /api/tools/execute` runs a tool without the model. The same gates apply —
it is a convenience, not a bypass. `GET /api/tools/schemas` returns exactly what
the model is shown, which is how you can confirm `confirmation_token` is absent
from the terminal schema.
