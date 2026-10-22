/**
 * Health, metrics, and the preflight report.
 *
 * Preflight is the same list the API refuses to start with in production, so it
 * is shown as a checklist rather than buried in a JSON blob.
 */

import { useState } from "react";

import { api, baseUrl, getToken, setToken } from "../client.js";
import { Button, Empty, Json, Note, StatusChip, Toolbar, useLoader } from "../ui.jsx";

export default function System({ status, onStatusChange }) {
  const health = useLoader(() => api.health());
  const metrics = useLoader(() => api.metrics());
  const preflight = useLoader(() => api.preflight());
  const auth = useLoader(() => api.authStatus());
  const [credential, setCredential] = useState(() => getToken() ?? "");
  const [saved, setSaved] = useState(null);

  function saveCredential(event) {
    event.preventDefault();
    setToken(credential.trim() || null);
    setSaved(credential.trim() ? "Credential stored for this browser." : "Credential cleared.");
    onStatusChange?.();
    health.refresh();
    metrics.refresh();
    preflight.refresh();
  }

  function refreshAll() {
    health.refresh();
    metrics.refresh();
    preflight.refresh();
    auth.refresh();
    onStatusChange?.();
  }

  const findings = preflight.data?.findings ?? [];

  return (
    <div className="stack">
      <section className="card">
        <Toolbar title="Health" hint={`API base: ${baseUrl}`}>
          <Button onClick={refreshAll}>Refresh</Button>
        </Toolbar>
        <Note kind="bad">{health.error}</Note>
        <div className="facts">
          <Fact label="Status" value={health.data?.status} />
          <Fact label="Environment" value={health.data?.environment} />
          <Fact label="Auth" value={health.data?.auth_enabled ? "enabled" : "disabled"} />
          <Fact label="Model" value={status?.model ?? "not configured"} />
          <Fact label="Provider" value={status?.provider} />
          <Fact label="Effort" value={status?.effort ?? "-"} />
          <Fact label="Uptime" value={seconds(metrics.data?.uptime_seconds)} />
          <Fact
            label="Scheduler"
            value={
              metrics.data?.scheduler
                ? `${metrics.data.scheduler.running ? "running" : "stopped"}, ${metrics.data.scheduler.ticks ?? 0} ticks`
                : "-"
            }
          />
          <Fact label="Sessions" value={metrics.data?.sessions} />
          <Fact label="Audit rows" value={metrics.data?.audit_entries_persisted} />
          <Fact label="Pending approvals" value={metrics.data?.pending_confirmations} />
          <Fact label="API keys" value={metrics.data?.api_keys} />
        </div>
      </section>

      <section className="card">
        <Toolbar
          title="Preflight"
          hint="Every insecure default still in place. In ENVIRONMENT=production the API refuses to start while a critical one remains."
        />
        <Note kind="bad">{preflight.error}</Note>
        {preflight.data ? (
          <p className="row">
            <StatusChip
              value={preflight.data.ready_for_production ? "ready" : `${findings.length} findings`}
            />
            {preflight.data.blocking ? (
              <span className="chip chip-bad">{preflight.data.blocking} blocking</span>
            ) : null}
          </p>
        ) : null}
        {findings.length === 0 && !preflight.busy ? (
          <Empty>No insecure defaults reported.</Empty>
        ) : (
          <ul className="findings">
            {findings.map((finding) => (
              <li key={finding.setting} className={`finding finding-${finding.severity}`}>
                <div className="finding-head">
                  <code>{finding.setting}</code>
                  <span className={finding.severity === "critical" ? "chip chip-bad" : "chip"}>
                    {finding.severity}
                  </span>
                </div>
                <p>{finding.detail}</p>
                <p className="hint">Fix: {finding.fix}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <Toolbar
          title="Credential"
          hint={
            auth.data?.auth_enabled
              ? "Auth is on: requests need an API key or JWT."
              : "Auth is off, so this is optional - every caller is a full admin until AUTH_ENABLED=true."
          }
        />
        <form className="form" onSubmit={saveCredential}>
          <label className="field">
            <span>API key (subh_...) or JWT</span>
            <input
              className="input"
              type="password"
              value={credential}
              onChange={(event) => setCredential(event.target.value)}
              placeholder="optional"
              autoComplete="off"
            />
          </label>
          <div className="row">
            <button className="btn btn-primary" type="submit">
              Save
            </button>
            <Button
              onClick={() => {
                setCredential("");
                setToken(null);
                setSaved("Credential cleared.");
              }}
            >
              Clear
            </Button>
          </div>
        </form>
        <Note>{saved}</Note>
      </section>

      <details className="card">
        <summary>Raw metrics</summary>
        {metrics.data ? <Json value={metrics.data} /> : <Empty>Unavailable.</Empty>}
      </details>
    </div>
  );
}

function Fact({ label, value }) {
  return (
    <div className="fact">
      <span className="fact-label">{label}</span>
      <span className="fact-value">{value ?? "-"}</span>
    </div>
  );
}

function seconds(value) {
  if (value === undefined || value === null) return "-";
  if (value < 90) return `${Math.round(value)}s`;
  if (value < 5400) return `${Math.round(value / 60)}m`;
  return `${(value / 3600).toFixed(1)}h`;
}
