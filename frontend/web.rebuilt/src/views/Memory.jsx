/**
 * Durable memory.
 *
 * Stored facts are injected into the system prompt, which makes this a
 * prompt-injection surface - so the exact text that gets injected is shown
 * here rather than left implicit.
 */

import { useState } from "react";

import { api } from "../client.js";
import { Button, Empty, Note, Toolbar, useLoader, when } from "../ui.jsx";

export default function Memory({ sessionId }) {
  const memories = useLoader(() => api.memory(sessionId), [sessionId]);
  const context = useLoader(() => api.request("/api/memory/context", { query: { session_id: sessionId } }), [sessionId]);
  const [content, setContent] = useState("");
  const [kind, setKind] = useState("fact");
  const [importance, setImportance] = useState(0.6);
  const [problem, setProblem] = useState(null);
  const [busy, setBusy] = useState(false);

  async function remember(event) {
    event.preventDefault();
    if (!content.trim()) return;
    setBusy(true);
    setProblem(null);
    try {
      await api.remember(content.trim(), sessionId, kind, Number(importance));
      setContent("");
      await Promise.all([memories.refresh(), context.refresh()]);
    } catch (error) {
      setProblem(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function forget(id) {
    setBusy(true);
    setProblem(null);
    try {
      await api.forget(id);
      await Promise.all([memories.refresh(), context.refresh()]);
    } catch (error) {
      setProblem(error.message);
    } finally {
      setBusy(false);
    }
  }

  const list = memories.data?.memories ?? [];
  const injected = context.data?.prompt_context;

  return (
    <div className="stack">
      <section className="card">
        <Toolbar title="Remember something" hint={`Session: ${sessionId}`} />
        <form className="form" onSubmit={remember}>
          <label className="field">
            <span>Fact</span>
            <input
              className="input"
              value={content}
              onChange={(event) => setContent(event.target.value)}
              placeholder="I prefer answers with the command shown first"
            />
          </label>
          <div className="form-row">
            <label className="field">
              <span>Kind</span>
              <select
                className="input"
                value={kind}
                onChange={(event) => setKind(event.target.value)}
              >
                <option value="fact">fact</option>
                <option value="episodic">episodic</option>
              </select>
            </label>
            <label className="field">
              <span>Importance ({Number(importance).toFixed(2)})</span>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={importance}
                onChange={(event) => setImportance(event.target.value)}
              />
            </label>
            <div className="field field-end">
              <button className="btn btn-primary" type="submit" disabled={busy}>
                Remember
              </button>
            </div>
          </div>
        </form>
        <Note kind="bad">{problem || memories.error}</Note>
      </section>

      <section className="card">
        <Toolbar title="Stored" hint="Newest first.">
          <Button onClick={memories.refresh}>Refresh</Button>
        </Toolbar>
        {list.length === 0 && !memories.busy ? (
          <Empty>Nothing stored for this session yet.</Empty>
        ) : (
          <ul className="memory-list">
            {list.map((memory) => (
              <li key={memory.id}>
                <div>
                  <p>{memory.content}</p>
                  <p className="hint">
                    <span className="chip">{memory.kind}</span> importance{" "}
                    {Number(memory.importance ?? 0).toFixed(2)} &middot; {when(memory.created_at)}
                  </p>
                </div>
                <Button variant="danger" onClick={() => forget(memory.id)} disabled={busy}>
                  Forget
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <Toolbar
          title="What the model actually sees"
          hint="Exactly the memory text appended to the system prompt. Framed as background, not instructions - framing is mitigation, not a guarantee."
        >
          <Button onClick={context.refresh}>Refresh</Button>
        </Toolbar>
        {injected ? (
          <pre className="json">{injected}</pre>
        ) : (
          <Empty>Nothing is being injected right now.</Empty>
        )}
      </section>
    </div>
  );
}
