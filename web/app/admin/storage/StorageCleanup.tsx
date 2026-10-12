"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/client";

interface Group {
  bucket: string;
  label: string;
  keepCount: number;
  keepBytes: number;
  remove: { key: string; size: number; modified: string }[];
  removeTotal: number;
  removeBytes: number;
}
interface Plan {
  groups: Group[];
  removeCount: number;
  removeBytes: number;
  versions: number;
  blocked?: string;
}

const mb = (b: number) => `${(b / 1024 / 1024).toFixed(b < 10 * 1024 * 1024 ? 2 : 1)} MB`;

/** Shows what is unused in R2 first; deletes only after the admin confirms. */
export default function StorageCleanup() {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      setPlan(await api<Plan>("/api/admin/storage"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    load();
  }, []);

  const clean = async () => {
    if (!plan || !window.confirm(`Delete ${plan.removeCount} unused files (${mb(plan.removeBytes)}) from Cloudflare R2? This cannot be undone.`)) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ deleted: number; bytes: number }>("/api/admin/storage", { method: "POST" });
      setDone(`Deleted ${r.deleted} files (${mb(r.bytes)}).`);
      await load();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <section>
      {error && <p className="msg err" role="alert">{error}</p>}
      {done && <p className="msg">{done}</p>}
      {!plan ? (
        <p className="muted">{busy ? "Checking the buckets…" : ""}</p>
      ) : plan.blocked ? (
        <p className="msg warn">{plan.blocked}</p>
      ) : (
        <>
          <table className="data">
            <thead>
              <tr><th>Bucket</th><th>Files</th><th>In use</th><th>Unused (can be deleted)</th></tr>
            </thead>
            <tbody>
              {plan.groups.map((g) => (
                <tr key={g.label}>
                  <td><code className="small">{g.bucket}</code></td>
                  <td>{g.label}</td>
                  <td>{g.keepCount} · {mb(g.keepBytes)}</td>
                  <td><strong>{g.removeTotal} · {mb(g.removeBytes)}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row" style={{ marginTop: 12, gap: 10, alignItems: "center" }}>
            <button className="btn" disabled={busy || !plan.removeCount} onClick={clean}>
              {busy ? "Working…" : plan.removeCount ? `Delete ${plan.removeCount} unused files (${mb(plan.removeBytes)})` : "Nothing to clean up"}
            </button>
            <button className="btn secondary" disabled={busy} onClick={load}>Check again</button>
            <span className="small muted">{plan.versions} versions checked.</span>
          </div>
          {plan.groups.some((g) => g.removeTotal > 0) && (
            <details style={{ marginTop: 12 }}>
              <summary>Show the unused files</summary>
              {plan.groups.filter((g) => g.removeTotal > 0).map((g) => (
                <div key={g.label} style={{ marginTop: 8 }}>
                  <strong>{g.label}</strong>
                  <ul className="small">
                    {g.remove.map((o) => (
                      <li key={o.key}><code>{o.key}</code> · {mb(o.size)}</li>
                    ))}
                    {g.removeTotal > g.remove.length && <li className="muted">… and {g.removeTotal - g.remove.length} more</li>}
                  </ul>
                </div>
              ))}
            </details>
          )}
        </>
      )}
    </section>
  );
}
