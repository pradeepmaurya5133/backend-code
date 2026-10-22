import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { createClient } from "@shared/api.js";
import Chat from "./components/Chat.jsx";
import {
  AuditPanel,
  MemoryPanel,
  PermissionsPanel,
  SystemPanel,
  TasksPanel,
  ToolsPanel,
} from "./components/Panels.jsx";
import { useVoice } from "./lib/useVoice.js";

const TABS = [
  ["chat", "Chat"],
  ["permissions", "Permissions"],
  ["tools", "Tools"],
  ["memory", "Memory"],
  ["tasks", "Automation"],
  ["audit", "Audit"],
  ["system", "System"],
];

// In dev, Vite proxies /api to the backend, so a relative base avoids CORS.
const API_BASE = import.meta.env.VITE_API_BASE ?? window.location.origin;

function newSessionId() {
  return `web-${Math.random().toString(36).slice(2, 8)}`;
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem("subh.token") || "");
  const [sessionId, setSessionId] = useState(
    () => localStorage.getItem("subh.session") || newSessionId()
  );
  const [tab, setTab] = useState("chat");
  const [messages, setMessages] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [info, setInfo] = useState(null);
  const [problem, setProblem] = useState(null);
  const [speakReplies, setSpeakReplies] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const submitRef = useRef(null);
  const api = useMemo(
    () => createClient({ baseUrl: API_BASE, getToken: () => token || null }),
    [token]
  );

  // A final transcript is handed to Chat's send handler.
  const voice = useVoice({
    onTranscript: (transcript) => submitRef.current?.(transcript),
  });

  useEffect(() => localStorage.setItem("subh.session", sessionId), [sessionId]);
  useEffect(() => {
    if (token) localStorage.setItem("subh.token", token);
    else localStorage.removeItem("subh.token");
  }, [token]);

  const refreshSessions = useCallback(async () => {
    try {
      setSessions((await api.sessions()).sessions ?? []);
    } catch {
      /* listing is non-critical */
    }
  }, [api]);

  // Load status once, so a missing backend or model is stated rather than implied.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await api.status();
        if (cancelled) return;
        setInfo(status);
        setProblem(
          status.configured
            ? null
            : "No language model is configured. Set ANTHROPIC_API_KEY in backend/.env and restart the API."
        );
      } catch (error) {
        if (!cancelled) setProblem(error.message);
      }
      await refreshSessions();
    })();
    return () => {
      cancelled = true;
    };
  }, [api, refreshSessions]);

  // Load a session's transcript when switching to it.
  const openSession = useCallback(
    async (id) => {
      setSessionId(id);
      setDrawerOpen(false);
      setTab("chat");
      try {
        const { messages: history } = await api.transcript(id);
        setMessages((history ?? []).map((m) => ({ role: m.role, text: m.text })));
      } catch {
        setMessages([]);
      }
    },
    [api]
  );

  async function startNewChat() {
    const id = newSessionId();
    setSessionId(id);
    setMessages([]);
    setDrawerOpen(false);
    setTab("chat");
    await refreshSessions();
  }

  return (
    <div className="app">
      <div
        className={`scrim ${drawerOpen ? "open" : ""}`}
        onClick={() => setDrawerOpen(false)}
        aria-hidden="true"
      />

      <aside className={`sidebar ${drawerOpen ? "open" : ""}`}>
        <div className="brand">
          <span className="mark">S</span>
          <span>
            Subh AI
            <small>{info?.configured ? info.model : "model not configured"}</small>
          </span>
        </div>

        <button className="primary" onClick={startNewChat}>
          + New chat
        </button>

        <div>
          <div className="meta" style={{ marginBottom: "0.4rem" }}>
            Sessions
          </div>
          {sessions.length === 0 ? (
            <div className="meta">No saved sessions yet.</div>
          ) : (
            <div className="list">
              {sessions.map((session) => (
                <button
                  key={session.session_id}
                  className="session"
                  aria-current={session.session_id === sessionId}
                  onClick={() => openSession(session.session_id)}
                >
                  <span className="title">{session.title || session.session_id}</span>
                  <span className="meta">
                    {session.messages} messages
                    {session.awaiting_confirmation ? " · needs approval" : ""}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div style={{ marginTop: "auto" }}>
          <label className="row" style={{ gap: "0.45rem", marginBottom: "0.5rem" }}>
            <input
              type="checkbox"
              checked={speakReplies}
              onChange={(event) => setSpeakReplies(event.target.checked)}
              style={{ width: "auto" }}
            />
            <span className="meta">Speak replies aloud</span>
          </label>
          <input
            placeholder="API key or token (optional)"
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
          <div className="meta" style={{ marginTop: "0.35rem" }}>
            Only needed when the backend has AUTH_ENABLED=true.
          </div>
        </div>
      </aside>

      <main className="main">
        <div className="topbar">
          <button
            className="menu-button"
            onClick={() => setDrawerOpen((open) => !open)}
            aria-label="Toggle sidebar"
          >
            ☰
          </button>
          <nav className="tabs" role="tablist">
            {TABS.map(([key, label]) => (
              <button
                key={key}
                className="tab"
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
              >
                {label}
              </button>
            ))}
          </nav>
          <span className="spacer" />
          {voice.listening && <span className="pill warn">listening</span>}
          {voice.speaking && <span className="pill on">speaking</span>}
        </div>

        {(problem || voice.error) && (
          <div style={{ padding: "0.75rem 1rem 0" }}>
            {problem && <div className="banner">{problem}</div>}
            {voice.error && <div className="banner error">{voice.error}</div>}
          </div>
        )}

        {tab === "chat" && (
          <Chat
            api={api}
            sessionId={sessionId}
            messages={messages}
            setMessages={setMessages}
            voice={voice}
            speakReplies={speakReplies && voice.synthesisSupported}
            onRefreshSessions={refreshSessions}
            submitRef={submitRef}
          />
        )}
        {tab === "permissions" && <PermissionsPanel api={api} />}
        {tab === "tools" && <ToolsPanel api={api} />}
        {tab === "memory" && <MemoryPanel api={api} sessionId={sessionId} />}
        {tab === "tasks" && <TasksPanel api={api} />}
        {tab === "audit" && <AuditPanel api={api} />}
        {tab === "system" && <SystemPanel api={api} />}
      </main>
    </div>
  );
}
