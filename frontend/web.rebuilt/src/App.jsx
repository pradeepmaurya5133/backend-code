/**
 * Subh AI web client.
 *
 * One responsive layout for desktop, tablet and phone. The tabs mirror the
 * backend's surface: a chat that carries approval cards, the tool/permission
 * gate, automation, memory, the audit trail and the preflight report.
 */

import { useCallback, useEffect, useState } from "react";

import { api, baseUrl } from "./client.js";
import Chat from "./views/Chat.jsx";
import Tools from "./views/Tools.jsx";
import Automation from "./views/Automation.jsx";
import Memory from "./views/Memory.jsx";
import Audit from "./views/Audit.jsx";
import System from "./views/System.jsx";

const SESSION_ID = "web";

const TABS = [
  { id: "chat", label: "Chat", Panel: Chat },
  { id: "tools", label: "Tools", Panel: Tools },
  { id: "automation", label: "Automation", Panel: Automation },
  { id: "memory", label: "Memory", Panel: Memory },
  { id: "audit", label: "Audit", Panel: Audit },
  { id: "system", label: "System", Panel: System },
];

export default function App() {
  const [tab, setTab] = useState("chat");
  const [status, setStatus] = useState(null);
  const [reachable, setReachable] = useState(null);
  const [problem, setProblem] = useState(null);

  const refreshStatus = useCallback(async () => {
    try {
      const next = await api.status();
      setStatus(next);
      setReachable(true);
      setProblem(
        next.configured
          ? null
          : "No model configured on the server. Set ANTHROPIC_API_KEY in backend/.env and restart - tools, memory and automation still work without it."
      );
    } catch (error) {
      setReachable(false);
      setStatus(null);
      setProblem(error.message);
    }
  }, []);

  useEffect(() => {
    refreshStatus();
    const timer = window.setInterval(refreshStatus, 20000);
    return () => window.clearInterval(timer);
  }, [refreshStatus]);

  const active = TABS.find((entry) => entry.id === tab) ?? TABS[0];
  const Panel = active.Panel;

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <h1>Subh AI</h1>
            <p className="brand-sub">The model asks. You decide.</p>
          </div>
        </div>

        <div
          className={`pill ${reachable === false ? "pill-bad" : status?.configured ? "pill-good" : "pill-warn"}`}
          title={reachable === false ? baseUrl : `${status?.provider ?? ""} ${status?.model ?? ""}`}
        >
          {reachable === false
            ? "API unreachable"
            : status?.configured
              ? (status.model ?? "model ready")
              : "model not configured"}
        </div>
      </header>

      <nav className="tabs" aria-label="Sections">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className={entry.id === tab ? "tab tab-active" : "tab"}
            aria-current={entry.id === tab ? "page" : undefined}
            onClick={() => setTab(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </nav>

      {problem ? (
        <p className={reachable === false ? "banner banner-bad" : "banner"}>{problem}</p>
      ) : null}

      <main className="panel">
        <Panel sessionId={SESSION_ID} status={status} onStatusChange={refreshStatus} />
      </main>
    </div>
  );
}
