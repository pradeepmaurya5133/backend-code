# Shared client layer

`api.js` is the single API client used by every Subh AI front end. The web app
imports it directly; the mobile (Expo) and desktop (Tauri) shells are intended to
import the same file so request shapes, auth handling and error semantics stay
identical across platforms.
