import { useEffect, useRef, useState } from "react";

/** Human-readable text for every agent outcome, so no status is a dead end. */
function describeOutcome(result) {
  switch (result.status) {
    case "completed":
      return result.answer || "Done.";
    case "awaiting_confirmation":
      return null; // rendered as an approval card instead
    case "clarification_needed":
      return result.question || "Could you give me more detail?";
    case "refused":
      return "I can't help with that one.";
    case "llm_not_configured":
      return "No language model is configured. Set ANTHROPIC_API_KEY in backend/.env and restart.";
    case "llm_unavailable":
      return `I couldn't reach the model: ${result.detail || "unknown error"}`;
    case "max_iterations_reached":
      return "That needed more steps than I'm allowed in one turn. Try narrowing it down.";
    case "nothing_to_resume":
      return "There's nothing waiting for approval.";
    default:
      return result.detail || `Unexpected status: ${result.status}`;
  }
}

function ToolTrace({ results }) {
  if (!results?.length) return null;
  return (
    <details className="card" style={{ marginTop: "0.5rem" }}>
      <summary className="meta">{results.length} tool call{results.length > 1 ? "s" : ""}</summary>
      <ul className="list" style={{ marginTop: "0.6rem" }}>
        {results.map((entry, index) => (
          <li key={index}>
            <div className="row between">
              <span className="name">{entry.tool}</span>
              <span className={`pill ${entry.result?.status === "ok" || entry.result?.status === "completed" ? "on" : "warn"}`}>
                {entry.result?.status}
              </span>
            </div>
            <div className="meta">{JSON.stringify(entry.arguments)}</div>
          </li>
        ))}
      </ul>
    </details>
  );
}

function PlanCard({ plan }) {
  if (!plan?.steps?.length) return null;
  return (
    <details className="card" style={{ marginTop: "0.5rem" }}>
      <summary className="meta">Plan — {plan.understanding}</summary>
      <ol style={{ margin: "0.6rem 0 0", paddingLeft: "1.2rem" }}>
        {plan.steps.map((step, index) => (
          <li key={index}>
            {step.description}
            {step.tool ? <span className="pill" style={{ marginLeft: 6 }}>{step.tool}</span> : null}
            {step.requires_approval ? <span className="pill warn" style={{ marginLeft: 6 }}>approval</span> : null}
          </li>
        ))}
      </ol>
    </details>
  );
}

export default function Chat({
  api,
  sessionId,
  messages,
  setMessages,
  voice,
  speakReplies,
  onRefreshSessions,
  submitRef,
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(null);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, pending]);

  function append(message) {
    setMessages((current) => [...current, message]);
  }

  function handleResult(result) {
    if (result.plan?.steps?.length || result.plan?.understanding) {
      append({ role: "plan", plan: result.plan });
    }
    if (result.status === "awaiting_confirmation") {
      setPending(result);
      append({
        role: "assistant",
        text: "I need approval before running that.",
        results: result.results,
      });
    } else {
      setPending(null);
      const text = describeOutcome(result);
      append({ role: "assistant", text, results: result.results });
      if (speakReplies && text) voice.speak(text);
    }
    onRefreshSessions?.();
  }

  async function send(text) {
    const message = (text ?? draft).trim();
    if (!message || busy) return;
    setDraft("");
    append({ role: "user", text: message });
    setBusy(true);
    try {
      handleResult(await api.run(message, sessionId));
    } catch (error) {
      append({ role: "system", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  async function decide(approve) {
    if (!pending?.confirmation_token) return;
    setBusy(true);
    try {
      if (approve) await api.approve(pending.confirmation_token);
      else await api.deny(pending.confirmation_token);
      append({ role: "system", text: approve ? "Approved." : "Denied." });
      // Resuming continues the parked turn on the server.
      handleResult(await api.resume(sessionId));
    } catch (error) {
      append({ role: "system", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  // The voice hook lives in App (the topbar needs its state), so Chat registers
  // its send handler for App to call when a final transcript arrives.
  useEffect(() => {
    if (submitRef) submitRef.current = (transcript) => send(transcript);
    return () => {
      if (submitRef) submitRef.current = null;
    };
  });

  const call = pending?.pending_call;
  const commandText = call?.arguments?.command || JSON.stringify(call?.arguments ?? {}, null, 2);

  return (
    <div className="chat">
      <div className="messages">
        {messages.length === 0 && (
          <div className="empty">
            <p style={{ fontSize: "1.05rem", marginBottom: "0.3rem" }}>Hello, I'm Subh AI.</p>
            <p>
              Ask me something, or tap the microphone and speak. I'll tell you when an action needs
              your approval before I run it.
            </p>
          </div>
        )}

        {messages.map((message, index) =>
          message.role === "plan" ? (
            <PlanCard key={index} plan={message.plan} />
          ) : (
            <div key={index} className={`bubble ${message.role}`}>
              {message.role !== "system" && (
                <span className="role">{message.role === "user" ? "You" : "Subh AI"}</span>
              )}
              {message.text}
              {message.role === "assistant" && <ToolTrace results={message.results} />}
            </div>
          )
        )}

        {pending && (
          <div className="card approval">
            <h3>Approval needed</h3>
            <p className="hint">
              Subh AI wants to use <strong>{call?.tool}</strong>. It has not run.
            </p>
            <code>{commandText}</code>
            <div className="row">
              <button className="primary" onClick={() => decide(true)} disabled={busy}>
                Approve and run
              </button>
              <button className="danger" onClick={() => decide(false)} disabled={busy}>
                Deny
              </button>
            </div>
          </div>
        )}

        {voice.interim && (
          <div className="bubble user" style={{ opacity: 0.6 }}>
            <span className="role">Listening…</span>
            {voice.interim}
          </div>
        )}
        {busy && <div className="bubble system">Subh AI is working…</div>}
        <div ref={endRef} />
      </div>

      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <button
          type="button"
          className={`mic ${voice.listening ? "active" : ""}`}
          onClick={() => (voice.listening ? voice.stopListening() : voice.startListening())}
          disabled={!voice.recognitionSupported}
          title={
            voice.recognitionSupported
              ? voice.listening
                ? "Stop listening"
                : "Speak to Subh AI"
              : "Speech recognition is not available in this browser"
          }
          aria-label={voice.listening ? "Stop listening" : "Start listening"}
        >
          {voice.listening ? "■" : "🎙"}
        </button>

        <textarea
          rows={1}
          value={draft}
          placeholder="Message Subh AI…"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
        />

        <button className="primary" type="submit" disabled={busy || !draft.trim()}>
          Send
        </button>
        {voice.speaking && (
          <button type="button" className="ghost" onClick={voice.stopSpeaking} title="Stop speaking">
            🔇
          </button>
        )}
      </form>
    </div>
  );
}
