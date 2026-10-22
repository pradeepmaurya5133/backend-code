# Subh AI — mobile & tablet client

Expo / React Native. Imports `frontend/shared/api.js`, the same client the web
app uses, so request shapes and error handling match across platforms.

```bash
cd frontend/mobile
npm install
npx expo start      # then press a (Android), i (iOS), or scan the QR code
```

**Not built or run in this repo's environment** — it needs an Android SDK or
Xcode, neither of which was available here. The code and config are complete,
but the build has not been exercised; expect to resolve the usual first-run
Expo/native issues.

`app.json` sets `extra.apiBase` to `http://10.0.2.2:8000`, which is how an
Android emulator reaches the host machine (`127.0.0.1` inside the emulator is
the emulator itself). For a physical device, change it to your machine's LAN
address and add that origin to `CORS_ORIGINS` on the backend.

Tablet layout comes from `ios.supportsTablet` plus the flex layout, which
expands to fill whatever viewport it is given.

Voice is not wired here. The web client uses the browser Web Speech API, which
React Native does not have; a native build would use `expo-speech` for output
plus a speech-recognition module for input, or post audio to
`POST /api/voice/audio` once a server-side STT provider is configured.
