# Subh AI — desktop client

A Tauri shell that loads the web client. The desktop app is the same React code,
packaged as a native window — so chat, voice, approvals and automation behave
identically to the browser.

**Not built in this repo's environment** — Tauri needs a Rust toolchain, which
was not available here. `tauri.conf.json` and `Cargo.toml` are complete and the
web client it wraps is built and verified.

## Build it

```bash
# Prerequisites: Rust (rustup.rs) and the Tauri CLI
cargo install tauri-cli

# 1. Build the web client the shell loads
cd frontend/web && npm install && npm run build

# 2. Run or package the desktop shell
cd ../desktop && cargo tauri dev        # development window
cargo tauri build                        # installers in src-tauri/target/release/bundle
```

## Why a Tauri shell rather than Electron

Tauri uses the OS webview instead of bundling Chromium, so the installer is a
few megabytes rather than a hundred-plus, and there is no second browser engine
to keep patched.

## Talking to the backend

`tauri.conf.json` restricts the shell's network access to `127.0.0.1:8000`, so a
compromised page in the webview cannot reach arbitrary hosts. The backend is a
separate process — start it first, or supervise it with your service manager.

For a packaged app aimed at non-technical users, the backend would normally be
bundled as a sidecar binary (`externalBin`) and started by the shell; that is
deliberately not configured here, because it needs a packaged Python runtime.
