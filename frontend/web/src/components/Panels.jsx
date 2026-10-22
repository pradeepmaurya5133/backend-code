import { useCallback, useEffect, useState } from "react";

/** Small helper for panels that just load a payload once and render it. */
function useLoader(loader, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await loader());
      setError(null);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    reload();
  }, [reload]);

  return { data, error, loading, reload };
}

function Status({ error, loading, children }) {
  if (error) return <div className="banner error">{error}</div>;
  if (loading) return <div className="empty">Loading…</div>;
  return children;
}

/* ---------- Permissions ---------- */

export function PermissionsPanel({ api }) {
  const { data, error, loading, reload } = useLoader(() => api.permissions(), [api]);
  const [busy, setBusy] = useState(null);

  async function toggle(permission, granted) {
    setBusy(permission);
    try {
      if (granted) await api.revoke(permission);
      else await api.grant(permission);
      await reload();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="panel">
      <div className="card">
        <h3>Permissions</h3>
        <p className="hint">
          Subh AI can only do what is switched on here. Anything that reaches outside the sandbox,
          writes, or deletes is off by default.
        </p>
        <Status error={error} loading={loading}>
          <ul className="list">
            {Object.entries(data?.permissions ?? {}).map(([permission, granted]) => (
              <li key={permission}>
                <div className="row between">
                  <div>
                    <div className="name">{permission}</div>
                    <div className="meta">{granted ? "Allowed" : "Blocked"}</div>
                  </div>
                  <button
                    className={granted ? "danger" : "primary"}
                    disabled={busy === permission}
                    onClick={() => toggle(permission, granted)}
                  >
                    {granted ? "Revoke" : "Grant"}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </Status>
      </div>
    </div>
  );
}

/* ---------- Tools ---------- */

export function ToolsPanel({ api }) {
  const { data, error, loading } = useLoader(() => api.tools(), [api]);
  return (
    <div className="panel">
      <div className="card">
        <h3>Tools</h3>
        <p className="hint">
          What Subh AI can request. Each call still passes the permission layer before anything runs.
        </p>
        <Status error={error} loading={loading}>
          <ul className="list">
            {(data?.tools ?? []).map((tool) => (
              <li key={tool.name}>
                <div className="name">{tool.name}</div>
                <div className="meta">{tool.description}</div>
                <div className="row" style={{ marginTop: "0.4rem" }}>
                  {tool.permissions.map((permission) => (
                    <span key={permission} className="pill">
                      {permission}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </Status>
      </div>
    </div>
  );
}

/* ---------- Memory ---------- */

export function MemoryPanel({ api, sessionId }) {
  const { data, error, loading, reload } = useLoader(
    () => api.memory(sessionId),
    [api, sessionId]
  );
  const [draft, setDraft] = useState("");

  async function add(event) {
    event.preventDefault();
    if (!draft.trim()) return;
    await api.remember(draft.trim(), sessionId, "fact", 0.7);
    setDraft("");
    await reload();
  }

  return (
    <div className="panel">
      <div className="card">
        <h3>Memory</h3>
        <p className="hint">
          Facts persist into future sessions and are shown to Subh AI as background. Episodic entries
          are a log of what it did.
        </p>
        <form className="row" onSubmit={add} style={{ marginBottom: "0.9rem" }}>
          <input
            value={draft}
            placeholder="Teach Subh AI something durable…"
            onChange={(event) => setDraft(event.target.value)}
            style={{ flex: 1, minWidth: "180px" }}
          />
          <button className="primary" type="submit" disabled={!draft.trim()}>
            Remember
          </button>
        </form>
        <Status error={error} loading={loading}>
          {(data?.memories ?? []).length === 0 ? (
            <div className="empty">Nothing remembered for this session yet.</div>
          ) : (
            <ul className="list">
              {data.memories.map((memory) => (
                <li key={memory.id}>
                  <div className="row between">
                    <div style={{ minWidth: 0 }}>
                      <div className="name">{memory.content}</div>
                      <div className="meta">
                        {memory.kind} · importance {memory.importance}
                      </div>
                    </div>
                    <button
                      className="danger ghost"
                      onClick={async () => {
                        await api.forget(memory.id);
                        await reload();
                      }}
                    >
                      Forget
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Status>
      </div>
    </div>
  );
}

/* ---------- Tasks ---------- */

const EMPTY_TASK = { name: "", prompt: "", schedule_kind: "once", interval_seconds: 3600, cron: "0 2 * * *" };

export function TasksPanel({ api }) {
  const { data, error, loading, reload } = useLoader(() => api.tasks(), [api]);
  const [form, setForm] = useState(EMPTY_TASK);
  const [message, setMessage] = useState(null);

  async function create(event) {
    event.preventDefault();
    const payload = {
      name: form.name,
      prompt: form.prompt,
      schedule_kind: form.schedule_kind,
      ...(form.schedule_kind === "interval" ? { interval_seconds: Number(form.interval_seconds) } : {}),
      ...(form.schedule_kind === "cron" ? { cron: form.cron } : {}),
    };
    const result = await api.createTask(payload);
    setMessage(result.status === "created" ? `Created "${result.task.name}".` : result.status);
    if (result.status === "created") setForm(EMPTY_TASK);
    await reload();
  }

  return (
    <div className="panel">
      <div className="card">
        <h3>Automation</h3>
        <p className="hint">
          Scheduled tasks run through the same agent, so they are just as gated — one that needs
          approval parks until you approve it.
        </p>
        {message && <div className="banner">{message}</div>}
        <form onSubmit={create} className="grid-2" style={{ marginBottom: "0.9rem" }}>
          <input
            placeholder="Task name"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            required
          />
          <select
            value={form.schedule_kind}
            onChange={(event) => setForm({ ...form, schedule_kind: event.target.value })}
          >
            <option value="once">Run once, now</option>
            <option value="interval">Every N seconds</option>
            <option value="cron">Cron schedule</option>
          </select>
          <input
            placeholder="What should Subh AI do?"
            value={form.prompt}
            onChange={(event) => setForm({ ...form, prompt: event.target.value })}
            required
            style={{ gridColumn: "1 / -1" }}
          />
          {form.schedule_kind === "interval" && (
            <input
              type="number"
              min="10"
              value={form.interval_seconds}
              onChange={(event) => setForm({ ...form, interval_seconds: event.target.value })}
            />
          )}
          {form.schedule_kind === "cron" && (
            <input
              placeholder="0 2 * * *"
              value={form.cron}
              onChange={(event) => setForm({ ...form, cron: event.target.value })}
            />
          )}
          <button className="primary" type="submit" style={{ gridColumn: "1 / -1" }}>
            Create task
          </button>
        </form>

        <Status error={error} loading={loading}>
          {(data?.tasks ?? []).length === 0 ? (
            <div className="empty">No tasks yet.</div>
          ) : (
            <ul className="list">
              {data.tasks.map((task) => (
                <li key={task.id}>
                  <div className="row between">
                    <div style={{ minWidth: 0 }}>
                      <div className="name">{task.name}</div>
                      <div className="meta">
                        {task.schedule_kind}
                        {task.cron ? ` (${task.cron})` : ""}
                        {task.interval_seconds ? ` (${task.interval_seconds}s)` : ""} · last:{" "}
                        {task.last_status}
                      </div>
                      <div className="meta">{task.prompt}</div>
                    </div>
                    <div className="row">
                      <span className={`pill ${task.enabled ? "on" : "off"}`}>
                        {task.enabled ? "enabled" : "paused"}
                      </span>
                      <button
                        onClick={async () => {
                          await api.runTask(task.id);
                          await reload();
                        }}
                      >
                        Run now
                      </button>
                      <button
                        onClick={async () => {
                          if (task.enabled) await api.disableTask(task.id);
                          else await api.enableTask(task.id);
                          await reload();
                        }}
                      >
                        {task.enabled ? "Pause" : "Resume"}
                      </button>
                      <button
                        className="danger ghost"
                        onClick={async () => {
                          await api.deleteTask(task.id);
                          await reload();
                        }}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Status>
      </div>
    </div>
  );
}

/* ---------- Audit ---------- */

export function AuditPanel({ api }) {
  const { data, error, loading, reload } = useLoader(() => api.audit(100), [api]);
  return (
    <div className="panel">
      <div className="card">
        <div className="row between">
          <div>
            <h3>Audit trail</h3>
            <p className="hint">Every permission decision, approval and tool outcome.</p>
          </div>
          <button onClick={reload}>Refresh</button>
        </div>
        <Status error={error} loading={loading}>
          <div className="scroller">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Actor</th>
                  <th>Action</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {(data?.entries ?? []).map((entry) => (
                  <tr key={entry.id ?? `${entry.timestamp}-${entry.action}`}>
                    <td>{(entry.timestamp || "").slice(11, 19)}</td>
                    <td>{entry.actor || entry.user_id}</td>
                    <td style={{ whiteSpace: "normal" }}>{entry.action}</td>
                    <td>{entry.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Status>
      </div>
    </div>
  );
}

/* ---------- System ---------- */

export function SystemPanel({ api }) {
  const { data, error, loading, reload } = useLoader(
    async () => ({
      metrics: await api.metrics(),
      preflight: await api.preflight(),
    }),
    [api]
  );

  return (
    <div className="panel">
      <Status error={error} loading={loading}>
        <div className="card">
          <div className="row between">
            <h3>System</h3>
            <button onClick={reload}>Refresh</button>
          </div>
          <div className="grid-2" style={{ marginTop: "0.6rem" }}>
            <div>
              <div className="meta">Model</div>
              <div className="name">{data?.metrics?.llm?.model ?? "not configured"}</div>
            </div>
            <div>
              <div className="meta">Scheduler</div>
              <div className="name">
                {data?.metrics?.scheduler?.running ? "running" : "stopped"} ·{" "}
                {data?.metrics?.scheduler?.ticks} ticks
              </div>
            </div>
            <div>
              <div className="meta">Sessions</div>
              <div className="name">{data?.metrics?.sessions}</div>
            </div>
            <div>
              <div className="meta">Audit entries</div>
              <div className="name">{data?.metrics?.audit_entries_persisted}</div>
            </div>
            <div>
              <div className="meta">Uptime</div>
              <div className="name">{Math.round(data?.metrics?.uptime_seconds ?? 0)}s</div>
            </div>
            <div>
              <div className="meta">Pending approvals</div>
              <div className="name">{data?.metrics?.pending_confirmations}</div>
            </div>
          </div>
        </div>

        <div className="card">
          <h3>Production readiness</h3>
          <p className="hint">
            Defaults are tuned for local development. These are the ones to change before deploying.
          </p>
          {data?.preflight?.ready_for_production ? (
            <div className="banner" style={{ borderColor: "var(--ok)" }}>
              No outstanding configuration issues.
            </div>
          ) : (
            <ul className="list">
              {(data?.preflight?.findings ?? []).map((finding) => (
                <li key={finding.setting}>
                  <div className="row between">
                    <div className="name">{finding.setting}</div>
                    <span className={`pill ${finding.severity === "critical" ? "warn" : ""}`}>
                      {finding.severity}
                    </span>
                  </div>
                  <div className="meta">{finding.detail}</div>
                  <div className="meta">Fix: {finding.fix}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Status>
    </div>
  );
}
