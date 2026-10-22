/**
 * Scheduled tasks (Phase 5): once, every N seconds, or a cron expression.
 *
 * A scheduled run goes through the same permission and confirmation gates as a
 * chat turn, so a task that needs approval parks until someone approves it.
 */

import { useState } from "react";

import { api } from "../client.js";
import { Button, Empty, Json, Note, StatusChip, Toolbar, useLoader, when } from "../ui.jsx";

const BLANK = {
  name: "",
  prompt: "",
  session_id: "scheduled",
  schedule_kind: "once",
  interval_seconds: 3600,
  cron: "0 9 * * *",
  max_retries: 2,
};

export default function Automation() {
  const tasks = useLoader(() => api.tasks());
  const [form, setForm] = useState(BLANK);
  const [problem, setProblem] = useState(null);
  const [outcome, setOutcome] = useState(null);
  const [busy, setBusy] = useState(false);

  function set(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function create(event) {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      const payload = {
        name: form.name.trim(),
        prompt: form.prompt.trim(),
        session_id: form.session_id.trim() || "scheduled",
        schedule_kind: form.schedule_kind,
        max_retries: Number(form.max_retries),
        interval_seconds:
          form.schedule_kind === "interval" ? Number(form.interval_seconds) : undefined,
        cron: form.schedule_kind === "cron" ? form.cron.trim() : undefined,
      };
      const created = await api.createTask(payload);
      if (created.status !== "created") {
        setProblem(`Rejected: ${created.status}${created.cron ? ` (${created.cron})` : ""}`);
      } else {
        setForm(BLANK);
      }
      await tasks.refresh();
    } catch (error) {
      setProblem(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function act(action, id) {
    setBusy(true);
    setProblem(null);
    setOutcome(null);
    try {
      const result = await action(id);
      if (result?.run_status) setOutcome(result);
      await tasks.refresh();
    } catch (error) {
      setProblem(error.message);
    } finally {
      setBusy(false);
    }
  }

  const scheduler = tasks.data?.scheduler;
  const list = tasks.data?.tasks ?? [];

  return (
    <div className="stack">
      <section className="card">
        <Toolbar
          title="Scheduler"
          hint={
            scheduler
              ? `${scheduler.running ? "Running" : "Stopped"}, tick every ${scheduler.tick_seconds ?? "?"}s`
              : "Status unavailable"
          }
        >
          <Button onClick={tasks.refresh}>Refresh</Button>
        </Toolbar>
        <Note kind="bad">{tasks.error || problem}</Note>

        {list.length === 0 && !tasks.busy ? (
          <Empty>No tasks yet. Create one below.</Empty>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Schedule</th>
                  <th>Next run</th>
                  <th>Last</th>
                  <th>State</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {list.map((task) => (
                  <tr key={task.id}>
                    <td>
                      <strong>{task.name}</strong>
                      <p className="hint">{task.prompt}</p>
                    </td>
                    <td>
                      {task.schedule_kind}
                      {task.schedule_kind === "interval" ? ` ${task.interval_seconds}s` : ""}
                      {task.schedule_kind === "cron" ? ` ${task.cron}` : ""}
                    </td>
                    <td>{when(task.next_run_at)}</td>
                    <td>
                      {task.last_status ? <StatusChip value={task.last_status} /> : "-"}
                      <p className="hint">{when(task.last_run_at)}</p>
                    </td>
                    <td>
                      <span className={task.enabled ? "chip chip-good" : "chip"}>
                        {task.enabled ? "enabled" : "disabled"}
                      </span>
                    </td>
                    <td className="row-actions">
                      <Button onClick={() => act(api.runTask, task.id)} disabled={busy}>
                        Run now
                      </Button>
                      <Button
                        onClick={() =>
                          act(task.enabled ? api.disableTask : api.enableTask, task.id)
                        }
                        disabled={busy}
                      >
                        {task.enabled ? "Disable" : "Enable"}
                      </Button>
                      <Button
                        variant="danger"
                        onClick={() => act(api.deleteTask, task.id)}
                        disabled={busy}
                      >
                        Delete
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {outcome ? <Json value={outcome} /> : null}
      </section>

      <section className="card">
        <Toolbar title="New task" hint="The prompt runs as a full agent turn when it fires." />
        <form className="form" onSubmit={create}>
          <label className="field">
            <span>Name</span>
            <input
              className="input"
              value={form.name}
              required
              onChange={(event) => set("name", event.target.value)}
              placeholder="Morning workspace summary"
            />
          </label>
          <label className="field">
            <span>Prompt</span>
            <textarea
              className="code-input"
              rows={3}
              value={form.prompt}
              required
              onChange={(event) => set("prompt", event.target.value)}
              placeholder="Summarise any new files in my workspace"
            />
          </label>
          <div className="form-row">
            <label className="field">
              <span>Schedule</span>
              <select
                className="input"
                value={form.schedule_kind}
                onChange={(event) => set("schedule_kind", event.target.value)}
              >
                <option value="once">once</option>
                <option value="interval">interval</option>
                <option value="cron">cron</option>
              </select>
            </label>
            {form.schedule_kind === "interval" ? (
              <label className="field">
                <span>Every (seconds)</span>
                <input
                  className="input"
                  type="number"
                  min="5"
                  value={form.interval_seconds}
                  onChange={(event) => set("interval_seconds", event.target.value)}
                />
              </label>
            ) : null}
            {form.schedule_kind === "cron" ? (
              <label className="field">
                <span>Cron</span>
                <input
                  className="input"
                  value={form.cron}
                  onChange={(event) => set("cron", event.target.value)}
                  placeholder="0 9 * * *"
                />
              </label>
            ) : null}
            <label className="field">
              <span>Max retries</span>
              <input
                className="input"
                type="number"
                min="0"
                max="10"
                value={form.max_retries}
                onChange={(event) => set("max_retries", event.target.value)}
              />
            </label>
          </div>
          <div className="row">
            <button className="btn btn-primary" type="submit" disabled={busy}>
              Create task
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
