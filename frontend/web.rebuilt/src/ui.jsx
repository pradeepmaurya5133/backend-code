/** Small pieces shared by the panels, so each view stays about its own data. */

import { useCallback, useEffect, useState } from "react";

/** Load something from the API, with the error and refresh plumbing done once. */
export function useLoader(load, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(true);

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      setData(await load());
      setError(null);
    } catch (cause) {
      setError(cause.message);
    } finally {
      setBusy(false);
    }
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, error, busy, refresh, setError };
}

export function Toolbar({ title, hint, children }) {
  return (
    <div className="toolbar">
      <div>
        <h2>{title}</h2>
        {hint ? <p className="hint">{hint}</p> : null}
      </div>
      {children ? <div className="toolbar-actions">{children}</div> : null}
    </div>
  );
}

export function Button({ variant = "", children, ...rest }) {
  return (
    <button type="button" className={`btn ${variant ? `btn-${variant}` : ""}`} {...rest}>
      {children}
    </button>
  );
}

export function Note({ kind = "", children }) {
  if (!children) return null;
  return <p className={`note ${kind ? `note-${kind}` : ""}`}>{children}</p>;
}

export function Empty({ children }) {
  return <p className="empty">{children}</p>;
}

export function Json({ value }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}

export function StatusChip({ value }) {
  const bad = /denied|error|refused|required|not_|fail|unavailable|unknown/.test(String(value));
  const good = /ok|completed|granted|approved|created|ran|success|ready|enabled/.test(String(value));
  return (
    <span className={`chip ${bad ? "chip-bad" : good ? "chip-good" : ""}`}>{String(value)}</span>
  );
}

/** Timestamps come back as ISO strings; show them in the reader's own zone. */
export function when(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}
