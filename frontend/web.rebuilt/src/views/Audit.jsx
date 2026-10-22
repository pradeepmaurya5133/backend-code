/** The audit trail: who asked for what, and what the gate decided. */

import { useState } from "react";

import { api } from "../client.js";
import { Button, Empty, Json, Note, StatusChip, Toolbar, useLoader, when } from "../ui.jsx";

export default function Audit() {
  const [limit, setLimit] = useState(50);
  const trail = useLoader(() => api.audit(limit), [limit]);

  const entries = trail.data?.entries ?? [];

  return (
    <section className="card">
      <Toolbar
        title="Audit trail"
        hint={
          trail.data
            ? `${trail.data.count} entries persisted, showing the newest ${entries.length}`
            : "Durable trail from the database, newest first."
        }
      >
        <select
          className="input input-slim"
          value={limit}
          onChange={(event) => setLimit(Number(event.target.value))}
        >
          {[25, 50, 100, 250].map((value) => (
            <option key={value} value={value}>
              last {value}
            </option>
          ))}
        </select>
        <Button onClick={trail.refresh}>Refresh</Button>
      </Toolbar>
      <Note kind="bad">{trail.error}</Note>

      {entries.length === 0 && !trail.busy ? (
        <Empty>Nothing recorded yet. Grant a permission or run a tool and it will show up here.</Empty>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Status</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry, index) => (
                <tr key={entry.id ?? index}>
                  <td className="nowrap">{when(entry.timestamp)}</td>
                  {/* Durable rows carry `actor`; the in-memory ring uses `user_id`. */}
                  <td>{entry.actor ?? entry.user_id ?? "-"}</td>
                  <td>
                    <code>{entry.action}</code>
                  </td>
                  <td>
                    <StatusChip value={entry.status} />
                  </td>
                  <td>{entry.detail ? <Json value={entry.detail} /> : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
