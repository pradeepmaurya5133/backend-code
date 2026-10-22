# Phase 4 — Application

React Web + Mobile + Tablet + Desktop.

One API, one shared client, three shells. `frontend/shared/api.js` is
dependency-free (plain `fetch`) precisely so Vite, Expo and Tauri can all import
the same file without a bundler-specific shim — request shapes, auth handling and
error semantics stay identical across platforms.

## Web — built and running

`frontend/web`, React 18 + Vite. **http://localhost:5173**

> Vite 5 binds IPv6 `localhost`, so `127.0.0.1:5173` will not connect. Use
> `localhost`.

Seven tabs: Chat, Permissions, Tools, Memory, Automation, Audit, System.

### Chat is where the trust boundary becomes visible

- **Approval cards.** When the agent needs permission, the chat shows the exact
  command in a monospace block with Approve and Deny. Nothing has run at that
  point. Approving calls `/api/confirmations/approve` then `/api/agent/resume`,
  which is the same flow the curl example uses.
- **Collapsible plan.** The structured plan from the planner, with a badge on
  steps that will need approval — so you see the shape of the work before it starts.
- **Tool trace.** Every call with its arguments and resulting status, collapsed by
  default. A refused call is visibly refused.
- **Voice.** Mic button; the agent speaks replies back. Toggleable in the sidebar.
- **Every status is rendered.** `describeOutcome()` has a branch for each agent
  outcome, so `llm_not_configured` produces *"Set ANTHROPIC_API_KEY in
  backend/.env and restart"* rather than a blank bubble.

### Responsive: one layout, three form factors

Not three codebases — a grid that collapses:

- **Desktop** (>900px): persistent sidebar beside the main panel.
- **Tablet / phone** (≤900px): the sidebar becomes a slide-over drawer with a
  scrim; the hamburger button appears.
- **Small phone** (≤560px): tighter padding, smaller base font, brand subtitle hidden.

Touch and mobile details that are easy to miss:

- Inputs are `font-size: 16px`, which is what stops iOS Safari zooming the page on
  focus.
- Buttons have a 40px minimum height.
- The composer uses `padding-bottom: max(0.75rem, env(safe-area-inset-bottom))`,
  keeping it clear of the iPhone home indicator.
- `viewport-fit=cover` so that inset actually applies.
- Light and dark both defined, via `prefers-color-scheme`.
- Wide content (the audit table) scrolls inside its own container rather than
  making the page scroll sideways.

### Dev proxy

`vite.config.js` proxies `/api` to `127.0.0.1:8000`, so development is
same-origin and no CORS round trip is involved. The production build talks to
`VITE_API_BASE`.

## Mobile and tablet — written, not built

`frontend/mobile`, Expo / React Native. Imports the same shared client. Chat plus
the approval flow, with native `FlatList` / `KeyboardAvoidingView`.

**Not built here: no Android SDK or Xcode was available.** The code and config
are complete but unexercised — expect the usual first-run native issues.

Two things worth knowing before running it:

- `app.json` sets `extra.apiBase` to `http://10.0.2.2:8000`, which is how an
  Android emulator reaches the host machine — `127.0.0.1` inside the emulator is
  the emulator. For a physical device use your LAN address and add it to
  `CORS_ORIGINS`.
- Tablet support comes from `ios.supportsTablet` plus the flex layout.

Voice is not wired on mobile: React Native has no Web Speech API. A native build
would use `expo-speech` for output plus a recognition module for input, or post
audio to `/api/voice/audio` once a server-side STT provider exists.

## Desktop — written, not built

`frontend/desktop`, a Tauri shell that loads the web build, so the desktop app is
the same verified React code in a native window.

**Not built here: Tauri needs a Rust toolchain, which was unavailable.**

Tauri rather than Electron because it uses the OS webview instead of bundling
Chromium — a few MB instead of 100+, and no second browser engine to patch. Its
CSP restricts `connect-src` to `127.0.0.1:8000`, so a compromised page in the
webview cannot reach arbitrary hosts.

The backend stays a separate process. Bundling it as a Tauri sidecar is the
natural next step for non-technical users, but needs a packaged Python runtime,
so it is deliberately not configured.

## Auth in the clients

The sidebar takes an API key or JWT, stored in `localStorage`. The shared client
routes it automatically: a value starting `subh_` goes in `X-API-Key`, anything
else as `Authorization: Bearer`. It is only needed when the backend has
`AUTH_ENABLED=true`.
