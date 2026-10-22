/**
 * The chat, including the approval gate.
 *
 * When a turn stops for confirmation the server returns a token bound to that
 * exact call; this view shows the call verbatim and only sends approve/deny,
 * then resumes the turn. The model never sees the token.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../client.js";
import { Button, Json, Note, StatusChip } from "../ui.jsx";
import { speak, cancelSpeech, useVoice } from "../useVoice.js";

export default function Chat({ sessionId, status }) {
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(null);
  const [plan, setPlan] = useState(null);
  const [usePlanner, setUsePlanner] = useState(true);
  const [speakReplies, setSpeakReplies] = useState(false);
  const endRef = useRef(null);

  const push = useCallback((message) => {
    setMessages((current) => [...current, { ...message, at: new Date().toISOString() }]);
  }, []);

  // A turn parked for approval survives a page reload, so pick it back up.
  useEffect(() => {
    let cancelled = false;
    api
      .pending(sessionId)
      .then((result) => {
        if (!cancelled && result.status === "awaiting_confirmation") setPending(result);
      })
      .catch(() => {
        /* the header already reports an unreachable API */
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, pending]);

  const handle = useCallback(
    (result, { spoken } = {}) => {
      setPlan(result.plan?.steps?.length ? result.plan : null);

      if (result.status === "awaiting_confirmation") {
        setPending(result);
        push({
          role: "assistant",
          text: result.detail || "I need your approval before running that.",
          status: result.status,
          results: result.results,
        });
        return;
      }

      setPending(null);
      const text =
        result.answer || result.question || result.reply || result.detail || result.status;
      push({ role: "assistant", text, status: result.status, results: result.results });
      if (speakReplies) speak(spoken || text);
    },
    [push, speakReplies]
  );

  const send = useCallback(
    async (text, { viaVoice = false } = {}) => {
      const message = (text ?? "").trim();
      if (!message || busy) return;
      setDraft("");
      cancelSpeech();
      push({ role: "user", text: message, viaVoice });
      setBusy(true);
      try {
        if (viaVoice) {
          const turn = await api.voiceTurn(message, sessionId);
          handle({ ...turn, answer: turn.reply }, { spoken: turn.spoken });
        } else {
          handle(await api.run(message, sessionId, usePlanner));
        }
      } catch (error) {
        push({ role: "system", text: error.message });
      } finally {
        setBusy(false);
      }
    },
    [busy, handle, push, sessionId, usePlanner]
  );

  const voice = useVoice({
    onTranscript: (transcript) => {
      setSpeakReplies(true);
      send(transcript, { viaVoice: true });
    },
  });

  async function decide(approve) {
    if (!pending?.confirmation_token) return;
    setBusy(true);
    try {
      const verdict = approve
        ? await api.approve(pending.confirmation_token)
        : await api.deny(pending.confirmation_token);
      push({ role: "system", text: `Confirmation ${verdict.status}.` });
      setPending(null);
      handle(await api.resume(sessionId));
    } catch (error) {
      push({ role: "system", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    try {
      await api.reset(sessionId);
      setMessages([]);
      setPending(null);
      setPlan(null);
    } catch (error) {
      push({ role: "system", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  const pendingCall = pending?.pending_call;

  return (
    <div className="chat">
      <div className="chat-controls">
        <label className="switch">
          <input
            type="checkbox"
            checked={usePlanner}
            onChange={(event) => setUsePlanner(event.target.checked)}
          />
          Plan first
        </label>
        <label className="switch">
          <input
            type="checkbox"
            checked={speakReplies}
            onChange={(event) => {
              setSpeakReplies(event.target.checked);
              if (!event.target.checked) cancelSpeech();
            }}
          />
          Speak replies
        </label>
        <span className="spacer" />
        {busy ? <span className="working">working...</span> : null}
        <Button onClick={reset} disabled={busy}>
          New session
        </Button>
      </div>

      <div className="transcript">
        {messages.length === 0 ? (
          <div className="welcome">
            <h2>Ask Subh AI something</h2>
            <p>
              Try <em>list the files in my workspace</em>. Anything that writes, deletes, runs a
              command or leaves the sandbox is off until you grant it in <strong>Tools</strong>, and
              a command still needs your approval on a card right here in the chat.
            </p>
            {status && !status.configured ? (
              <p className="hint">
                Without a model key the agent replies <code>llm_not_configured</code>; the Tools tab
                can still drive each tool directly.
              </p>
            ) : null}
          </div>
        ) : null}

        {messages.map((message, index) => (
          <Message key={index} message={message} />
        ))}

        {pending ? (
          <div className="approval">
            <div className="approval-head">
              <strong>Approval needed</strong>
              <span className="token">{pending.confirmation_token}</span>
            </div>
            <p className="hint">This is the exact call that will run if you approve it.</p>
            <pre className="command">
              {pendingCall?.arguments?.command ??
                `${pendingCall?.tool ?? "tool"} ${JSON.stringify(pendingCall?.arguments ?? {})}`}
            </pre>
            <div className="approval-actions">
              <Button variant="primary" onClick={() => decide(true)} disabled={busy}>
                Approve
              </Button>
              <Button variant="danger" onClick={() => decide(false)} disabled={busy}>
                Deny
              </Button>
            </div>
          </div>
        ) : null}

        <div ref={endRef} />
      </div>

      {plan ? (
        <details className="plan">
          <summary>
            Plan <StatusChip value={plan.status ?? "ok"} /> &middot; {plan.steps.length} step
            {plan.steps.length === 1 ? "" : "s"}
          </summary>
          <ol>
            {plan.steps.map((step, index) => (
              <li key={index}>
                {typeof step === "string" ? step : (step.description ?? JSON.stringify(step))}
              </li>
            ))}
          </ol>
        </details>
      ) : null}

      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          send(draft);
        }}
      >
        <input
          className="input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Message Subh AI..."
          aria-label="Message"
          autoFocus
        />
        {voice.supported ? (
          <Button
            variant={voice.listening ? "danger" : ""}
            onClick={voice.toggle}
            title={voice.listening ? "Stop listening" : "Speak instead of typing"}
            aria-pressed={voice.listening}
          >
            {voice.listening ? "Listening..." : "Speak"}
          </Button>
        ) : null}
        <button className="btn btn-primary" type="submit" disabled={busy || !draft.trim()}>
          Send
        </button>
      </form>
      <Note kind="bad">{voice.error}</Note>
    </div>
  );
}

function Message({ message }) {
  const used = message.results?.filter(Boolean) ?? [];
  return (
    <div className={`bubble bubble-${message.role}`}>
      {message.viaVoice ? <span className="via">spoken</span> : null}
      <div className="bubble-text">{message.text}</div>
      {message.status && message.status !== "completed" ? (
        <StatusChip value={message.status} />
      ) : null}
      {used.length ? (
        <details className="tool-calls">
          <summary>
            {used.length} tool call{used.length === 1 ? "" : "s"}
          </summary>
          {used.map((entry, index) => (
            <div key={index} className="tool-call">
              <div className="tool-call-head">
                <code>{entry.tool}</code>
                <StatusChip value={entry.result?.status ?? "?"} />
              </div>
              <Json value={entry.arguments} />
              <Json value={entry.result} />
            </div>
          ))}
        </details>
      ) : null}
    </div>
  );
}
