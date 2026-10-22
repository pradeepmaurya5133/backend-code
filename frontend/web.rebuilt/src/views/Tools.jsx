/**
 * Tools and the permission gate.
 *
 * Granting is deliberately explicit: nothing that writes, deletes, runs a
 * command or leaves the sandbox is on by default, and the same gates apply when
 * a tool is driven from here rather than by the model.
 */

import { useState } from "react";

import { api } from "../client.js";
import { Button, Empty, Json, Note, StatusChip, Toolbar, useLoader } from "../ui.jsx";

const EXAMPLES = {
  filesystem: { operation: "list", path: "." },
  terminal: { command: "python --version" },
  web: { operation: "fetch", url: "https://example.com" },
  http_api: { method: "GET", url: "https://api.example.com/status" },
  memory: { operation: "recall" },
};

export default function Tools({ sessionId }) {
  const tools = useLoader(() => api.tools());
  const permissions = useLoader(() => api.permissions());
  const [selected, setSelected] = useState("filesystem");
  const [args, setArgs] = useState(() => JSON.stringify(EXAMPLES.filesystem, null, 2));
  const [result, setResult] = useState(null);
  const [problem, setProblem] = useState(null);
  const [busy, setBusy] = useState(false);

  async function toggle(name, granted) {
    setProblem(null);
    try {
      const outcome = granted ? await api.revoke(name) : await api.grant(name);
      if (outcome.status?.startsWith("unknown")) setProblem(`Unknown permission: ${name}`);
      await permissions.refresh();
    } catch (error) {
      setProblem(error.message);
    }
  }

  function pick(name) {
    setSelected(name);
    setResult(null);
    setArgs(JSON.stringify(EXAMPLES[name] ?? {}, null, 2));
  }

  async function execute() {
    setBusy(true);
    setProblem(null);
    setResult(null);
    let parsed;
    try {
      parsed = args.trim() ? JSON.parse(args) : {};
    } catch {
      setProblem("Arguments must be valid JSON.");
      setBusy(false);
      return;
    }
    try {
      setResult(await api.executeTool(selected, parsed, sessionId));
    } catch (error) {
      setProblem(error.message);
    } finally {
      setBusy(false);
      permissions.refresh();
    }
  }

  const grants = permissions.data?.permissions ?? {};

  return (
    <div className="stack">
      <section className="card">
        <Toolbar
          title="Permissions"
          hint="Off by default. Granting a capability is the first of three gates; a terminal command still needs an allowlisted executable and your approval."
        >
          <Button onClick={permissions.refresh}>Refresh</Button>
        </Toolbar>
        <Note kind="bad">{permissions.error || problem}</Note>
        <div className="grants">
          {Object.entries(grants).map(([name, granted]) => (
            <label key={name} className={granted ? "grant grant-on" : "grant"}>
              <input type="checkbox" checked={granted} onChange={() => toggle(name, granted)} />
              <code>{name}</code>
              <span className="grant-state">{granted ? "granted" : "off"}</span>
            </label>
          ))}
          {!permissions.busy && Object.keys(grants).length === 0 ? (
            <Empty>No permissions reported.</Empty>
          ) : null}
        </div>
      </section>

      <section className="card">
        <Toolbar
          title="Tools"
          hint="What the model is offered, and which permission each call needs."
        />
        <Note kind="bad">{tools.error}</Note>
        <div className="tool-grid">
          {(tools.data?.tools ?? []).map((tool) => (
            <button
              key={tool.name}
              type="button"
              className={tool.name === selected ? "tool-card tool-card-active" : "tool-card"}
              onClick={() => pick(tool.name)}
            >
              <div className="tool-card-head">
                <code>{tool.name}</code>
                {tool.permissions.every((permission) => grants[permission]) ? (
                  <span className="chip chip-good">ready</span>
                ) : (
                  <span className="chip">gated</span>
                )}
              </div>
              <p>{tool.description}</p>
              <div className="perm-list">
                {tool.permissions.map((permission) => (
                  <span key={permission} className={grants[permission] ? "chip chip-good" : "chip"}>
                    {permission}
                  </span>
                ))}
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="card">
        <Toolbar
          title="Run a tool directly"
          hint="Bypasses the model, not the gates. Useful for checking a capability without spending tokens."
        />
        <label className="field">
          <span>
            Arguments for <code>{selected}</code> (JSON)
          </span>
          <textarea
            className="code-input"
            rows={6}
            value={args}
            spellCheck={false}
            onChange={(event) => setArgs(event.target.value)}
          />
        </label>
        <div className="row">
          <Button variant="primary" onClick={execute} disabled={busy}>
            {busy ? "Running..." : "Execute"}
          </Button>
          {result?.status ? <StatusChip value={result.status} /> : null}
        </div>
        {result ? <Json value={result} /> : null}
      </section>
    </div>
  );
}
