"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/client";
import { slimHvcFile } from "@/lib/hvcSlim";
import { PRODUCT_TYPES, type Gazetteer, type HvcSummary, type Payload, type ProductType } from "@/lib/types";
import { Legend } from "@/components/Legend";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

const INPUTS: Record<ProductType, { field: string; label: string; template?: string; help?: string }[]> = {
  envi: [
    { field: "drought", label: "Drought forecast per province (CSV)", template: "envi_drought" },
    { field: "damage", label: "Historical El Niño damage per municipality (ha)", template: "envi_damage" },
    { field: "crops", label: "Standing rice and corn per municipality (ha)", template: "envi_crops" },
    {
      field: "hvc",
      label: "High-value crops – HVCDP Regional Summary (optional)",
      help: "The workbook exactly as HVCDP sends it. The HVC standing area is computed for the “standing crops as of” date from the planting and target-harvest dates; only the needed columns are uploaded.",
    },
    {
      field: "livestock",
      label: "Livestock & poultry inventory – heads per municipality (optional)",
      template: "livestock",
      help: "The DA inventory form or the template. Heads are converted to livestock units (TLU) and combined with the crop area into the exposure indicator.",
    },
  ],
  rainfall_dekad: [{ field: "file", label: "10-day rainfall per municipality (mm)", template: "rainfall_dekad" }],
  rainfall_seasonal: [{ field: "file", label: "Monthly rainfall per municipality (mm)", template: "rainfall_seasonal" }],
  drought: [{ field: "file", label: "Drought categories per province and month", template: "drought" }],
};

const STEPS = ["Period", "Upload", "Validation", "Preview", "Save draft"];

const DATASET_LABELS: Record<string, string> = {
  drought: "Drought forecast", damage: "Historical damage", crops: "Standing rice and corn",
  hvc: "High-value crops (HVCDP)", livestock: "Livestock & poultry",
};

const iso = (d: Date) => d.toISOString().slice(0, 10);
/** Last day of the month before `d` – the usual standing-crops cutoff of a monthly issue. */
const endOfPreviousMonth = (d: Date) => iso(new Date(Date.UTC(d.getFullYear(), d.getMonth(), 0)));
/** Last day of the latest quarter that has ended – the usual livestock inventory date. */
const endOfLastQuarter = (d: Date) => iso(new Date(Date.UTC(d.getFullYear(), Math.floor(d.getMonth() / 3) * 3, 0)));

/** HVC standing area and the area still in the field in each outlook month (El Niño timing). */
function HvcTable({ s }: { s: HvcSummary }) {
  const ha = (v: number) => `${Math.round(v).toLocaleString()} ha`;
  return (
    <div className="table-scroll" style={{ marginTop: 6 }}>
      <p className="small">
        <strong>{ha(s.standing_ha)}</strong> of HVC standing on {s.as_of}: {ha(s.short_cycle_ha)} short-cycle (vegetables, root
        crops, spices, cut flowers) + {ha(s.perennial_ha)} tree / plantation crops. {s.n_records.toLocaleString()} planting records,{" "}
        {s.first_planting} – {s.last_planting}.
      </p>
      <table className="data">
        <thead>
          <tr>
            <th>Outlook month</th>
            <th>Short-cycle HVC in the field</th>
            <th>Due for harvest that month</th>
            <th>Tree / plantation crops</th>
          </tr>
        </thead>
        <tbody>
          {s.outlook.map((o) => (
            <tr key={o.month}>
              <td>{o.label}</td>
              <td>{ha(o.short_cycle_ha)}</td>
              <td>{ha(o.harvest_due_ha)}</td>
              <td>{ha(o.perennial_ha)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small muted">
        By province: {Object.entries(s.by_province).map(([p, v]) => `${p} ${ha(v)}`).join(" · ")}. By group:{" "}
        {Object.entries(s.by_group).map(([g, v]) => `${g} ${ha(v)}`).join(" · ")}.
      </p>
    </div>
  );
}

interface Preview {
  payload: Payload;
  uploadId: string;
  files: any[];
  sig: string | null;
  // ENVI: historical damage / livestock taken from an earlier issue
  reused?: Record<string, { filename: string; issue: string; as_of?: string | null }> | null;
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
    weights: type === "envi" ? { hazard: 0.7, damage: 0.15, crops: 0.15 } : undefined, // drought 70 %, damage 15 %, exposure 15 %
    classification: type === "envi" ? "equal" : undefined,
    // ENVI exposure: rice/corn (and HVC) standing date, livestock inventory date, livestock share of exposure
    crops_as_of: type === "envi" ? endOfPreviousMonth(new Date()) : undefined,
    livestock_as_of: type === "envi" ? "" : undefined,
    livestock_share: type === "envi" ? 0.25 : undefined,
    manual_matches: {},
  }));
  const [files, setFiles] = useState<Record<string, File>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [layerId, setLayerId] = useState<string | undefined>();
  const [fromFeed, setFromFeed] = useState(false);
  // drought forecast fetched from PAGASA DroughtCaster (ENVI "drought" file, drought product "file")
  const [dcInfo, setDcInfo] = useState<string | null>(null);
  const droughtField = type === "envi" ? "drought" : type === "drought" ? "file" : null;
  const fetchDroughtcaster = async () => {
    if (!droughtField) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<{
        csv: string; filename: string; issued: string; period_start: string; period_end: string; months: string[];
        assessment?: Record<string, string | null>; assessment_month?: string | null;
      }>(
        "/api/admin/droughtcaster",
        { method: "POST" },
      );
      setFiles((fs) => ({ ...fs, [droughtField]: new File([r.csv], r.filename, { type: "text/csv" }) }));
      setSettings((s) => ({
        ...s,
        issue_date: r.issued || s.issue_date,
        period_start: r.period_start || s.period_start,
        ...(type === "envi" ? { period_end: r.period_end || s.period_end } : {}),
        // observed situation (PAGASA assessment) for the "current condition" on the summary page
        current_condition:
          r.assessment && r.assessment_month
            ? {
                month: r.assessment_month,
                label: new Date(`${r.assessment_month}-01T00:00:00`).toLocaleString("en", { month: "long", year: "numeric" }),
                by_province: r.assessment,
                source: "PAGASA DroughtCaster (observed)",
              }
            : undefined,
      }));
      setPreview(null);
      const mon = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleString("en", { month: "long", year: "numeric" });
      setDcInfo(`PAGASA DroughtCaster outlook issued ${r.issued}, ${mon(r.months[0])} – ${mon(r.months[r.months.length - 1])} (${r.filename}). The period and issue date were set from it.`);
    } catch (e) {
      setError(`DroughtCaster: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  // ENVI monthly update: the historical damage / livestock files the server reuses when none is uploaded
  type ReuseInfo = { filename: string; issue: string; status: string; as_of: string | null } | null;
  const [reuseAll, setReuseAll] = useState<{ damage: ReuseInfo; livestock: ReuseInfo } | undefined>(undefined);
  const reuse = reuseAll === undefined ? undefined : reuseAll.damage;
  const [useLivestock, setUseLivestock] = useState(true);
  useEffect(() => {
    if (type !== "envi") return;
    api<{ damage: ReuseInfo; livestock: ReuseInfo }>("/api/admin/reuse")
      .then((r) => {
        setReuseAll(r);
        // a reused livestock inventory keeps the date it was entered with
        if (r.livestock?.as_of) setSettings((s) => ({ ...s, livestock_as_of: s.livestock_as_of || r.livestock!.as_of }));
      })
      .catch(() => setReuseAll({ damage: null, livestock: null }));
  }, [type]);
  // HVCDP workbook reduced in the browser to the columns the ENVI needs
  const [hvcNote, setHvcNote] = useState<string | null>(null);
  const pickHvc = async (f: File) => {
    setBusy(true);
    setError(null);
    setHvcNote(null);
    try {
      const r = await slimHvcFile(f);
      setFiles((fs) => ({ ...fs, hvc: r.file }));
      setHvcNote(r.note);
    } catch (e) {
      if (f.size <= 4 * 1024 * 1024) setFiles((fs) => ({ ...fs, hvc: f }));
      setError(`HVCDP file: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

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
      if (type === "envi" && !useLivestock) form.set("reuse_livestock", "0");
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
                <label htmlFor={`w-${k}`}>
                  Weight – {k === "hazard" ? "drought forecast" : k === "damage" ? "historical damage" : "exposure (crops + livestock)"}
                </label>
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
                  setPreview(null);
                  if (inp.field === "hvc") {
                    if (f) return void pickHvc(f);
                    setHvcNote(null);
                  }
                  setFiles((fs) => {
                    const n = { ...fs };
                    if (f) n[inp.field] = f;
                    else delete n[inp.field];
                    return n;
                  });
                }}
              />
              {inp.template && <a href={templateUrl(inp.template)}>Download template</a>}
              {inp.field === droughtField && (
                <button type="button" className="btn secondary" disabled={busy} onClick={fetchDroughtcaster}>
                  {busy ? "Fetching…" : "Fetch from PAGASA DroughtCaster"}
                </button>
              )}
            </div>
            {inp.field === droughtField && files[inp.field] && dcInfo && files[inp.field].name.startsWith("droughtcaster_") && (
              <p className="hint">✓ {dcInfo}</p>
            )}
            {inp.help && <p className="help">{inp.help}</p>}
            {inp.field === "crops" && (
              <div className="row" style={{ marginTop: 6 }}>
                <label className="row" htmlFor="crops-as-of">
                  Standing crops as of{" "}
                  <input id="crops-as-of" type="date" value={settings.crops_as_of ?? ""} onChange={(e) => set("crops_as_of", e.target.value)} />
                </label>
                <span className="small muted">Rice and corn inventory date; the HVC standing area is computed for the same date.</span>
              </div>
            )}
            {inp.field === "hvc" && hvcNote && files.hvc && <p className="hint">✓ {hvcNote}</p>}
            {inp.field === "livestock" && (files.livestock || (reuseAll?.livestock && useLivestock)) && (
              <div className="row" style={{ marginTop: 6 }}>
                <label className="row" htmlFor="lv-as-of">
                  Inventory as of{" "}
                  <input id="lv-as-of" type="date" value={settings.livestock_as_of ?? ""} onChange={(e) => set("livestock_as_of", e.target.value)} />
                </label>
                {!settings.livestock_as_of && (
                  <button type="button" className="btn secondary" onClick={() => set("livestock_as_of", endOfLastQuarter(new Date()))}>
                    End of last quarter
                  </button>
                )}
                <label className="row" htmlFor="lv-share">
                  Livestock share of exposure{" "}
                  <input
                    id="lv-share"
                    type="number"
                    step="0.05"
                    min={0}
                    max={1}
                    style={{ width: 80 }}
                    value={settings.livestock_share}
                    onChange={(e) => set("livestock_share", Number(e.target.value))}
                  />
                </label>
                <span className="small muted">
                  Exposure = {(1 - settings.livestock_share).toFixed(2)} × crop area + {Number(settings.livestock_share).toFixed(2)} ×
                  livestock, each normalized 0–1 (hectares and heads are never added).
                </span>
              </div>
            )}
            {type === "envi" && inp.field === "livestock" && !files.livestock && reuseAll?.livestock && (
              <div className="hint">
                <label className="row">
                  <input type="checkbox" checked={useLivestock} onChange={(e) => setUseLivestock(e.target.checked)} />
                  <span>
                    Reuse <strong>{reuseAll.livestock.filename}</strong> from the {reuseAll.livestock.issue} issue (the inventory is
                    quarterly). Upload a file only for a new quarter.
                  </span>
                </label>
              </div>
            )}
            {type === "envi" && inp.field === "damage" && !files.damage && reuse !== undefined && (
              <p className={`hint ${reuse ? "" : "warn"}`}>
                {reuse ? (
                  <>
                    Optional for the monthly update: <strong>{reuse.filename}</strong> from the {reuse.issue} issue
                    {reuse.status !== "published" ? ` (${reuse.status})` : ""} is reused. Upload a file only to replace it.
                  </>
                ) : (
                  "Required: there is no earlier ENVI issue to reuse it from."
                )}
              </p>
            )}
          </div>
        ))}
        {type === "envi" && (
          <p className="hint">
            Monthly update: upload the new drought forecast, the new standing rice and corn and the latest HVCDP Regional Summary; the
            season ENVI and the monthly maps are recomputed from them. Historical damage and livestock are reused until you upload new
            files.
          </p>
        )}
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
              {type === "envi" && <h3>{DATASET_LABELS[ds] ?? ds}</h3>}
              {preview.reused?.[ds] && (
                <p className="msg">Reused from the {preview.reused[ds].issue} issue: {preview.reused[ds].filename}</p>
              )}
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
              {rep.hvc_summary && <HvcTable s={rep.hvc_summary} />}
              {rep.livestock_summary && (
                <p className="small" style={{ marginTop: 6 }}>
                  {Object.entries(rep.livestock_summary.heads as Record<string, number>)
                    .filter(([, v]) => v > 0)
                    .map(([k, v]) => `${k} ${v.toLocaleString()}`)
                    .join(" · ")}{" "}
                  → <strong>{Math.round(rep.livestock_summary.tlu_total).toLocaleString()} TLU</strong> (livestock units).
                </p>
              )}
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
