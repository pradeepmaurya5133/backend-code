# Phase 3 — Voice

Speech → AI → Action → Speech.

The middle of that pipeline is the ordinary agent. Speaking a command gets no
more authority than typing it: the transcript goes through the same planner,
permission gate, allowlist and approval flow. A spoken "delete everything" still
produces an approval card.

## Two modes

**`browser`** (default) — the client does recognition and synthesis with the Web
Speech API. The server only ever receives text. This needs **no API keys and no
audio upload**, which is why it is the default and why voice works out of the box.

**`server`** — audio is posted to the API, a provider transcribes it, the agent
runs, and a provider synthesises the reply. The interfaces are defined
(`SpeechToText`, `TextToSpeech`); no cloud provider is wired in, so this mode
reports `stt_not_configured` until one is registered.

## Making answers listenable

A written answer is often a bad spoken one, so `speakable()` adapts it:

- Code blocks are not read character by character — they are replaced with a note
  that the code is in the written response.
- Long answers are cut at a sentence boundary, not mid-word, with a note that
  there is more in the full response.
- The cap is 700 characters, far below the text limit.

Both forms come back: `reply` for the screen, `spoken` for the speaker.

## Every outcome has something to say

An agent turn can end in eight different ways, and silence is a bad answer to any
of them. `_reply_text()` maps each one:

| Status | Spoken as |
|---|---|
| `completed` | The answer |
| `awaiting_confirmation` | A request for approval, naming the command |
| `clarification_needed` | The question the planner asked |
| `refused` | A short decline |
| `llm_not_configured` | That the model needs an API key |
| `llm_unavailable` | That the model could not be reached |
| `max_iterations_reached` | That the task needed too many steps |

## Client behaviour

`frontend/web/src/lib/useVoice.js`:

- Recognition **stops speech synthesis first** — otherwise the microphone
  transcribes the agent's own voice back into a new request.
- Interim results stream into the UI, so it is visibly listening.
- A blocked microphone becomes a readable message, not a console error.
- `aborted` errors are ignored; that is what a deliberate stop looks like.
- Support is *reported*, not assumed — Chrome and Edge have recognition, Firefox
  does not. The mic button disables itself and typing always works.
- `prefers-reduced-motion` disables the pulsing mic animation.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/voice/status` | Mode, and whether providers are configured |
| POST | `/api/voice/turn` | Browser mode: send a transcript, get `reply` + `spoken` |
| POST | `/api/voice/audio` | Server mode: upload audio (10 MB cap) |

## Not verified

Server-side STT/TTS has test doubles only — no provider keys were available.
Browser mode was verified through the running app.
