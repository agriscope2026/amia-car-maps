"use client";

import { useState } from "react";
import { api } from "@/lib/client";

export function UnpublishButton({ id }: { id: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      className="btn secondary"
      disabled={busy}
      onClick={async () => {
        if (!confirm("Remove this product from the public dashboard?")) return;
        setBusy(true);
        try {
          await api(`/api/admin/versions/${id}/unpublish`, { method: "POST" });
          window.location.reload();
        } catch (e) {
          alert((e as Error).message);
          setBusy(false);
        }
      }}
    >
      Unpublish
    </button>
  );
}

export function FeedButton({ type = "rainfall_dekad", label }: { type?: string; label?: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div>
      <button
        className="btn"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            const res = await api("/api/admin/feed", { method: "POST", json: { type } });
            sessionStorage.setItem("feedPreview", JSON.stringify(res));
            window.location.href = `/admin/new/${type}?from=feed`;
          } catch (e) {
            setError((e as Error).message);
            setBusy(false);
          }
        }}
      >
        {busy ? "Fetching (can take a minute)…" : label ?? "Fetch latest 10-day rainfall forecast"}
      </button>
      {error && <p className="msg err">{error}</p>}
    </div>
  );
}

export function DeleteVersionButton({ id, label, small }: { id: string; label: string; small?: boolean }) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      className={`btn danger${small ? " small" : ""}`}
      disabled={busy}
      onClick={async () => {
        if (!confirm(`Delete ${label} permanently? Its maps and files are removed too. This cannot be undone.`)) return;
        setBusy(true);
        try {
          await api(`/api/admin/versions/${id}`, { method: "DELETE" });
          window.location.href = "/admin";
        } catch (e) {
          alert((e as Error).message);
          setBusy(false);
        }
      }}
    >
      {busy ? "Deleting…" : "Delete"}
    </button>
  );
}

interface TcAuto {
  enabled: boolean;
  updated_by?: string;
  updated_at?: string;
  last_run?: { at: string; result: string; ok: boolean; bulletin?: string };
}

const when = (iso?: string) =>
  iso ? new Date(iso).toLocaleString("en-PH", { timeZone: "Asia/Manila", dateStyle: "medium", timeStyle: "short" }) : "";

/** Automatic Special Advisory: on / off (admins), the last run, and "Run now". */
export function TcAutoSwitch({ initial, canEdit }: { initial: TcAuto; canEdit: boolean }) {
  const [s, setS] = useState<TcAuto>(initial);
  const [busy, setBusy] = useState<"" | "save" | "run">("");
  const [error, setError] = useState<string | null>(null);
  const save = async (enabled: boolean) => {
    if (enabled && !confirm("Publish every new PAGASA bulletin automatically and delete the older advisories? " +
      "Nobody reviews the signals before they go live.")) return;
    setBusy("save");
    setError(null);
    try {
      setS(await api("/api/admin/tc-auto", { method: "PUT", json: { enabled } }));
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy("");
  };
  return (
    <div className="tc-auto">
      <div role="radiogroup" aria-label="Automatic updating" className="tc-auto-options">
        <label className={!s.enabled ? "on" : ""}>
          <input type="radio" name="tc-auto" checked={!s.enabled} disabled={!canEdit || !!busy} onChange={() => save(false)} />
          <span><strong>Off</strong> – an admin fetches, checks and publishes each bulletin</span>
        </label>
        <label className={s.enabled ? "on" : ""}>
          <input type="radio" name="tc-auto" checked={s.enabled} disabled={!canEdit || !!busy} onChange={() => save(true)} />
          <span>
            <strong>Automatic</strong> – 3 minutes after each PAGASA bulletin (5 AM, 11 AM, 5 PM, 11 PM) the new advisory is
            made, published, and the older one deleted
          </span>
        </label>
      </div>
      {s.updated_by && <p className="muted small">Last changed by {s.updated_by}, {when(s.updated_at)}.</p>}
      {s.last_run && (
        <p className={`msg ${s.last_run.ok ? "ok" : "err"}`}>
          Last run {when(s.last_run.at)}{s.last_run.bulletin ? ` · ${s.last_run.bulletin}` : ""}: {s.last_run.result}
        </p>
      )}
      {canEdit && (
        <button
          className="btn secondary"
          disabled={!!busy}
          onClick={async () => {
            setBusy("run");
            setError(null);
            try {
              const res = await api("/api/admin/tc-auto", { method: "POST" });
              setS(res.setting);
              if (res.published) window.location.reload();
            } catch (e) {
              setError((e as Error).message);
            }
            setBusy("");
          }}
        >
          {busy === "run" ? "Fetching, exporting and publishing (a few minutes)…" : "Run now"}
        </button>
      )}
      {error && <p className="msg err">{error}</p>}
    </div>
  );
}
