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
