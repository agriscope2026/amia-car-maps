"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/client";
import { PRODUCT_TYPES, type Gazetteer, type Payload, type ProductType } from "@/lib/types";
import { Legend } from "@/components/Legend";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

const INPUTS: Record<ProductType, { field: string; label: string; template: string }[]> = {
  envi: [
    { field: "drought", label: "Drought forecast per province (CSV)", template: "envi_drought" },
    { field: "damage", label: "Historical El Niño damage per municipality (ha)", template: "envi_damage" },
    { field: "crops", label: "Standing crops per municipality (ha)", template: "envi_crops" },
  ],
  rainfall_dekad: [{ field: "file", label: "10-day rainfall per municipality (mm)", template: "rainfall_dekad" }],
  rainfall_seasonal: [{ field: "file", label: "Monthly rainfall per municipality (mm)", template: "rainfall_seasonal" }],
  drought: [{ field: "file", label: "Drought categories per province and month", template: "drought" }],
};

const STEPS = ["Period", "Upload", "Validation", "Preview", "Save draft"];

interface Preview {
  payload: Payload;
  uploadId: string;
  files: any[];
  sig: string | null;
}

function reportsOf(type: ProductType, payload: Payload | null): [string, any][] {
  if (!payload?.report) return [];
  return type === "envi" ? Object.entries(payload.report) : [[type, payload.report]];
}

/** Values read from PAGASA's table images, for the admin to compare with the images before publishing. */
function PagasaCheck({ info }: { info: { table: any[]; images: Record<string, string>; page: string; as_of?: string } }) {
  const months: string[] = [...new Set(info.table.map((r) => r.month as string))];
  const provinces: string[] = [...new Set(info.table.map((r) => r.province as string))];
  const cell = (p: string, m: string) => info.table.find((r) => r.province === p && r.month === m);
  const mon = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleString("en", { month: "short", year: "2-digit" });
  return (
    <div className="pagasa-check">
      <p className="msg warn">
        Check these values against PAGASA&apos;s tables before publishing:{" "}
        {Object.entries(info.images).map(([k, u]) => (
          <a key={k} href={u} target="_blank" rel="noreferrer" style={{ marginRight: 12 }}>
            {k === "mm" ? "Forecast rainfall (mm) table" : "% of normal table"} ↗
          </a>
        ))}
        <a href={info.page} target="_blank" rel="noreferrer">PAGASA seasonal forecast page ↗</a>
      </p>
      <div className="table-scroll">
        <table className="data">
          <thead>
            <tr>
              <th>Province</th>
              {months.map((m) => (
                <th key={m}>{mon(m)}<br /><span className="small muted">min · mean · max · %N</span></th>
              ))}
            </tr>
          </thead>
          <tbody>
            {provinces.map((p) => (
              <tr key={p}>
                <th>{p}</th>
                {months.map((m) => {
                  const c = cell(p, m);
                  return (
                    <td key={m}>
                      <span className="small muted">{c?.min ?? "–"}</span> · <strong>{c?.mean ?? "–"}</strong> ·{" "}
                      <span className="small muted">{c?.max ?? "–"}</span>
                      {c?.pct_normal != null && <span className="small"> · {c.pct_normal}%</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function UploadWizard({ type, geo }: { type: ProductType; geo: Gazetteer }) {
  const meta = PRODUCT_TYPES.find((t) => t.id === type)!;
  const today = new Date().toISOString().slice(0, 10);
  const [settings, setSettings] = useState<Record<string, any>>(() => ({
    issue_date: today,
    period_start: type === "rainfall_dekad" ? today : "2026-10",
    period_end: type === "rainfall_dekad" ? "" : "2027-03",
    source: "",
    max_warn_mm: type === "rainfall_dekad" ? 500 : undefined,
    weights: type === "envi" ? { hazard: 0.5, damage: 0.25, crops: 0.25 } : undefined, // drought 50 %, damage 25 %, crops 25 %
    classification: type === "envi" ? "equal" : undefined,
    manual_matches: {},
  }));
  const [files, setFiles] = useState<Record<string, File>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [layerId, setLayerId] = useState<string | undefined>();
  const [fromFeed, setFromFeed] = useState(false);

  // a feed fetch from the admin home arrives through sessionStorage
  useEffect(() => {
    if (!["rainfall_dekad", "rainfall_seasonal"].includes(type) || !window.location.search.includes("from=feed")) return;
    const raw = sessionStorage.getItem("feedPreview");
    if (!raw) return;
    sessionStorage.removeItem("feedPreview");
    const res = JSON.parse(raw) as Preview;
    setPreview(res);
    setFromFeed(true);
    const p = res.payload;
    if (p.period) setSettings((s) => ({ ...s, period_start: p.period.start, period_end: p.period.end, issue_date: p.issued }));
  }, [type]);

  const step = !preview ? (Object.keys(files).length ? 1 : 0) : !preview.payload.ok ? 2 : 3;
  const payload = preview?.payload ?? null;
  const layer = useMemo(() => payload?.layers?.find((l) => l.id === layerId) ?? payload?.layers?.[0] ?? null, [payload, layerId]);
  const set = (k: string, v: any) => setSettings((s) => ({ ...s, [k]: v }));

  const validate = async (extra: Record<string, any> = {}) => {
    setBusy(true);
    setError(null);
    try {
      const s = { ...settings, ...extra };
      const form = new FormData();
      form.set("settings", JSON.stringify(s));
      if (preview?.uploadId) form.set("uploadId", preview.uploadId);
      for (const [k, f] of Object.entries(files)) form.set(k, f, f.name);
      const res = await api<Preview>(`/api/admin/preview/${type}`, { method: "POST", body: form });
      setSettings(s);
      setPreview(res);
      setFromFeed(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // automatic source instead of an upload (PAGASA seasonal forecast / 10-day feed)
  const fetchAuto = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api<Preview>("/api/admin/feed", { method: "POST", json: { type } });
      setPreview(res);
      setFromFeed(true);
      const p = res.payload;
      if (p?.period) setSettings((s) => ({ ...s, period_start: p.period.start.slice(0, type === "rainfall_seasonal" ? 7 : 10), period_end: p.period.end.slice(0, type === "rainfall_seasonal" ? 7 : 10), issue_date: p.issued }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const assign = (dataset: string, raw: string, key: string) => {
    const mm = { ...(settings.manual_matches ?? {}), [`${dataset}|${raw}`]: key };
    validate({ manual_matches: mm });
  };

  const save = async () => {
    if (!preview?.sig) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ id: string }>("/api/admin/drafts", {
        method: "POST",
        json: {
          payload: preview.payload,
          sig: preview.sig,
          uploadId: preview.uploadId,
          files: preview.files,
          settings: {
            ...settings,
            recommendations_draft: preview.payload.recommendations_draft ?? preview.payload.texts?.recommendations,
            crop_advice_draft: preview.payload.crop_advice_draft,
          },
        },
      });
      window.location.href = `/admin/versions/${res.id}`;
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const templateUrl = (t: string) =>
    `/api/templates/${t}?period_start=${encodeURIComponent(settings.period_start ?? "")}&period_end=${encodeURIComponent(settings.period_end ?? "")}`;

  return (
    <main className="page">
      <h1>New: {meta.label}</h1>
      <ol className="steps">
        {STEPS.map((s, i) => (
          <li key={s} className={i === step ? "on" : i < step ? "done" : ""}>
            {i + 1}. {s}
          </li>
        ))}
      </ol>

      <section>
        <h2>1. Period and source</h2>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="issue">Issue date (“as of”)</label>
            <input id="issue" type="date" value={settings.issue_date} onChange={(e) => set("issue_date", e.target.value)} />
          </div>
          {type === "rainfall_dekad" ? (
            <>
              <div className="field">
                <label htmlFor="ps">Dekad start</label>
                <input id="ps" type="date" value={settings.period_start} onChange={(e) => set("period_start", e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="pe">Dekad end</label>
                <input id="pe" type="date" value={settings.period_end} onChange={(e) => set("period_end", e.target.value)} />
                <p className="help">e.g. October 1–10, 2026</p>
              </div>
              <div className="field">
                <label htmlFor="mx">Warn above (mm per dekad)</label>
                <input id="mx" type="number" min={1} value={settings.max_warn_mm} onChange={(e) => set("max_warn_mm", Number(e.target.value))} />
              </div>
            </>
          ) : (
            <>
              <div className="field">
                <label htmlFor="ps">First month</label>
                <input id="ps" type="month" value={settings.period_start} onChange={(e) => set("period_start", e.target.value)} />
              </div>
              {type !== "drought" && (
                <div className="field">
                  <label htmlFor="pe">Last month</label>
                  <input id="pe" type="month" value={settings.period_end} onChange={(e) => set("period_end", e.target.value)} />
                </div>
              )}
            </>
          )}
          <div className="field">
            <label htmlFor="src">Source (optional)</label>
            <input id="src" value={settings.source} onChange={(e) => set("source", e.target.value)} placeholder="e.g. DOST-PAGASA" />
          </div>
        </div>
        {type === "envi" && (
          <div className="form-grid" style={{ marginTop: 12 }}>
            {(["hazard", "damage", "crops"] as const).map((k) => (
              <div className="field" key={k}>
                <label htmlFor={`w-${k}`}>Weight – {k === "hazard" ? "drought forecast" : k === "damage" ? "historical damage" : "standing crops"}</label>
                <input
                  id={`w-${k}`}
                  type="number"
                  step="0.01"
                  min={0}
                  max={1}
                  value={Number(settings.weights[k]).toFixed(2)}
                  onChange={(e) => set("weights", { ...settings.weights, [k]: Number(e.target.value) })}
                />
              </div>
            ))}
            <div className="field">
              <label htmlFor="cls">Classification</label>
              <select id="cls" value={settings.classification} onChange={(e) => set("classification", e.target.value)}>
                <option value="equal">Equal intervals (0.2)</option>
                <option value="jenks">Natural breaks (Jenks)</option>
                <option value="quantile">Quantiles</option>
              </select>
              <p className="help">
                Weights must total 1 (now {(settings.weights.hazard + settings.weights.damage + settings.weights.crops).toFixed(2)}).
              </p>
            </div>
          </div>
        )}
      </section>

      <section>
        <h2>2. Upload</h2>
        {fromFeed && (
          <p className="msg ok">
            Loaded from {type === "rainfall_seasonal" ? "PAGASA's seasonal forecast page" : "the 10-day rainfall feed"}. You can
            still upload a file instead.
          </p>
        )}
        {(type === "rainfall_seasonal" || type === "rainfall_dekad") && (
          <div className="source-choice">
            <strong>Or get the data automatically:</strong>{" "}
            <button className="btn secondary" disabled={busy} onClick={fetchAuto}>
              {busy ? "Fetching (can take a minute)…" : type === "rainfall_seasonal" ? "Fetch from PAGASA (CAR only)" : "Fetch the 10-day forecast feed"}
            </button>
          </div>
        )}
        {INPUTS[type].map((inp) => (
          <div className="field" key={inp.field} style={{ marginBottom: 12 }}>
            <label htmlFor={`f-${inp.field}`}>{inp.label}</label>
            <div className="row">
              <input
                id={`f-${inp.field}`}
                type="file"
                accept=".csv,.xlsx,.xls"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  setFiles((fs) => {
                    const n = { ...fs };
                    if (f) n[inp.field] = f;
                    else delete n[inp.field];
                    return n;
                  });
                }}
              />
              <a href={templateUrl(inp.template)}>Download template</a>
            </div>
          </div>
        ))}
        <button className="btn" disabled={busy || !Object.keys(files).length} onClick={() => validate()}>
          {busy ? "Checking…" : "Validate"}
        </button>
        {error && <p className="msg err" role="alert">{error}</p>}
      </section>

      {preview && (
        <section>
          <h2>3. Validation report</h2>
          {(payload as any)?.pagasa?.table?.length > 0 && <PagasaCheck info={(payload as any).pagasa} />}
          {reportsOf(type, payload).map(([ds, rep]) => (
            <div key={ds} style={{ marginBottom: 14 }}>
              {type === "envi" && <h3>{ds}</h3>}
              {rep.n_data_rows !== undefined && (
                <p className="small muted">
                  {rep.filename}: {rep.n_data_rows} rows, {rep.n_matched} matched, {rep.n_unmatched} unmatched, {rep.n_subtotal_rows} subtotal rows
                  skipped. Columns: {(rep.columns ?? []).join(", ")}.
                </p>
              )}
              {(rep.errors ?? []).map((m: string, i: number) => (
                <p key={`e${i}`} className="msg err">{m}</p>
              ))}
              {(rep.warnings ?? []).map((m: string, i: number) => (
                <p key={`w${i}`} className="msg warn">{m}</p>
              ))}
              {!(rep.errors ?? []).length && !(rep.warnings ?? []).length && <p className="msg ok">No problems found.</p>}
              {(rep.unmatched ?? []).length > 0 && (
                <table className="data">
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Name in file</th>
                      <th>Assign to</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rep.unmatched.map((u: any) => (
                      <tr key={u.row}>
                        <td>{u.row}</td>
                        <td>{u.raw_name}</td>
                        <td>
                          <select defaultValue="" onChange={(e) => e.target.value && assign(ds, u.raw_name, e.target.value)} aria-label={`Assign ${u.raw_name}`}>
                            <option value="">— choose —</option>
                            <optgroup label="Suggestions">
                              {u.suggestions.map((s: any) => (
                                <option key={s.area_key} value={s.area_key}>
                                  {s.label} ({Math.round(s.score * 100)}%)
                                </option>
                              ))}
                            </optgroup>
                            <optgroup label="All municipalities">
                              {geo.gazetteer.map((g) => (
                                <option key={g.area_key} value={g.area_key}>
                                  {g.name} ({g.province})
                                </option>
                              ))}
                            </optgroup>
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </section>
      )}

      {payload?.ok && layer && (
        <section>
          <h2>4. Preview</h2>
          <p>
            <strong>{payload.title}</strong> – {payload.subtitle}
          </p>
          {payload.layers.length > 1 && (
            <select value={layer.id} onChange={(e) => setLayerId(e.target.value)} style={{ maxWidth: 360, marginBottom: 8 }}>
              {payload.layers.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.label}
                </option>
              ))}
            </select>
          )}
          <div className="row" style={{ alignItems: "flex-start" }}>
            <div className="preview-map" style={{ flex: "1 1 520px" }}>
              <MapView
                bounds={geo.bounds}
                payload={payload}
                layer={layer}
                crops={null}
                showCrops={false}
                cropMode="circles"
                irrigation={null}
                showIrrigation={false}
                irrTypes={[]}
                basemap="light"
              />
            </div>
            <div style={{ flex: "0 1 260px" }}>
              <Legend layer={layer} />
            </div>
          </div>
        </section>
      )}

      {payload?.ok && (
        <section>
          <h2>5. Save as draft</h2>
          <p className="muted">Next you can edit the title, notes and recommendations, generate the exports and publish.</p>
          <button className="btn" disabled={busy || !preview?.sig} onClick={save}>
            Save draft
          </button>
        </section>
      )}
    </main>
  );
}
