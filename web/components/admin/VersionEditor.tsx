"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { api } from "@/lib/client";
import { PRODUCT_TYPES, type Gazetteer, type Texts } from "@/lib/types";
import { fmtDate } from "@/lib/format";
import { Legend } from "@/components/Legend";
import { Downloads } from "@/components/Downloads";
import { DeleteVersionButton } from "@/app/admin/actions";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

const FIELDS: { key: keyof Texts; label: string; rows?: number; help?: string }[] = [
  { key: "title", label: "Title" },
  { key: "subtitle", label: "Subtitle (validity period and “as of” date)" },
  { key: "notes", label: "Notes", rows: 3 },
  { key: "disclaimer", label: "Disclaimer", rows: 3 },
  { key: "sources", label: "Sources", rows: 2 },
  { key: "recommendations", label: "Agricultural recommendations", rows: 10, help: "One item per line, starting with “-”. The slide shows a condensed version and the poster shows the full text." },
];

// farm recommendations (10-day, seasonal, drought): printed under the legend of every map of the product
const FARM_FIELDS: { key: keyof Texts; crop: string; label: string }[] = [
  { key: "advice_rice", crop: "rice", label: "Farm recommendation – Rice" },
  { key: "advice_corn", crop: "corn", label: "Farm recommendation – Corn" },
  { key: "advice_hvc", crop: "hvc", label: "Farm recommendation – HVC (high-value crops)" },
];

export default function VersionEditor({ version, role, geo }: { version: any; role: string; geo: Gazetteer }) {
  const payload = version.payload;
  const live = version.status === "published";
  // drafts: editors and admins; published versions: admins (changes go live immediately)
  const editable = version.status === "draft" || (live && role === "admin");
  const [stale, setStale] = useState<boolean>(!!version.exports?.stale);
  const [texts, setTexts] = useState<Texts>(payload.texts);
  const [saved, setSaved] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const running = version.exports?.pending_job ?? (version.exports?.job_id && !version.exports?.downloads ? version.exports.job_id : null);
  const [job, setJob] = useState<any>(running ? { id: running, status: "running", progress: [] } : null);
  const [downloads, setDownloads] = useState<any[]>(version.exports?.downloads ?? []);
  const [layerId, setLayerId] = useState<string>(payload.layers[0]?.id);
  const layer = payload.layers.find((l: any) => l.id === layerId) ?? payload.layers[0];
  const draft = version.settings?.recommendations_draft;
  const cropDraft: Record<string, string> = version.settings?.crop_advice_draft ?? {};
  const hasFarm = ["rainfall_dekad", "rainfall_seasonal", "drought"].includes(version.type);
  const canOverlay = ["rainfall_seasonal", "drought", "envi"].includes(version.type);
  const [cropList, setCropList] = useState<string[]>(version.settings?.crop_overlay_crops ?? []);
  const [cropInfo, setCropInfo] = useState<{ crops: string[]; colors?: Record<string, string>; as_of: string } | null>(null);
  useEffect(() => {
    if (canOverlay) fetch("/api/public/crops").then((r) => r.json()).then(setCropInfo).catch(() => undefined);
  }, [canOverlay]);

  // poll the export job
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") return;
    const t = setInterval(async () => {
      try {
        const j = await api(`/api/admin/jobs/${job.id}?version=${version.id}`);
        setJob(j);
        if (j.status === "done") {
          const v = await api(`/api/admin/versions/${version.id}`);
          setDownloads(v.exports?.downloads ?? []);
          setStale(!!v.exports?.stale);
        }
      } catch (e) {
        setError((e as Error).message);
      }
    }, 2000);
    return () => clearInterval(t);
  }, [job, version.id]);

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const saveTexts = () =>
    run("save", async () => {
      await api(`/api/admin/versions/${version.id}`, { method: "PATCH", json: { texts } });
      setSaved(true);
      if (live) setStale(true); // the live files keep the old text until they are regenerated
      else setDownloads([]); // draft: exports must be regenerated
    });

  const exportNow = () =>
    run("export", async () => {
      if (!saved) await api(`/api/admin/versions/${version.id}`, { method: "PATCH", json: { texts } });
      setSaved(true);
      const r = await api(`/api/admin/versions/${version.id}/export`, {
        method: "POST",
        json: canOverlay ? { crop_overlay: cropList } : {},
      });
      if (!live) setDownloads([]); // published: current files stay downloadable until the new ones are ready
      setJob({ id: r.job, status: "queued", progress: [] });
    });

  const publish = () =>
    run("publish", async () => {
      if (!confirm("Publish this version to the public dashboard? Any earlier published version of this product will be archived.")) return;
      await api(`/api/admin/versions/${version.id}/publish`, { method: "POST" });
      window.location.reload();
    });

  const unpublish = () =>
    run("unpublish", async () => {
      if (!confirm("Remove this version from the public dashboard?")) return;
      await api(`/api/admin/versions/${version.id}/unpublish`, { method: "POST" });
      window.location.reload();
    });

  const typeLabel = PRODUCT_TYPES.find((t) => t.id === version.type)?.label;
  const lastSteps: any[] = job?.progress ?? [];

  return (
    <main className="page">
      <p>
        <a href="/admin">← Products</a>
      </p>
      <h1>
        {typeLabel} · {payload.period.label}
      </h1>
      <p className="muted">
        As of {fmtDate(payload.issued)} · version {version.version} · <span className={`status ${version.status}`}>{version.status}</span> · by {version.author}
        {payload.method?.fetched_from && <> · from the feed {payload.method.fetched_from}</>}
      </p>
      {error && <p className="msg err" role="alert">{error}</p>}

      <section>
        <h2>Map</h2>
        {payload.layers.length > 1 && (
          <select value={layer.id} onChange={(e) => setLayerId(e.target.value)} style={{ maxWidth: 360, marginBottom: 8 }}>
            {payload.layers.map((l: any) => (
              <option key={l.id} value={l.id}>
                {l.label}
              </option>
            ))}
          </select>
        )}
        <div className="row" style={{ alignItems: "flex-start" }}>
          <div className="preview-map" style={{ flex: "1 1 520px" }}>
            <MapView bounds={geo.bounds} payload={payload} layer={layer} crops={null} showCrops={false} cropMode="circles" irrigation={null} showIrrigation={false} irrTypes={[]} basemap="light" />
          </div>
          <div style={{ flex: "0 1 260px" }}>
            <Legend layer={layer} />
          </div>
        </div>
      </section>

      <section>
        <h2>Text</h2>
        {live && editable && (
          <p className="msg warn">
            This version is <strong>live on the dashboard</strong>. Saved text changes, including the recommendations, appear
            there immediately. Then click <strong>Regenerate exports</strong> so the images, PDFs and presentation show them too.
          </p>
        )}
        {!editable && (
          <p className="msg warn">
            {live ? "Only administrators can edit a published version." : "Archived versions are read-only."}
          </p>
        )}
        <div className="form-grid" style={{ gridTemplateColumns: "1fr" }}>
          {FIELDS.map((f) => (
            <div className="field" key={f.key}>
              <label htmlFor={f.key}>{f.label}</label>
              {f.rows ? (
                <textarea id={f.key} rows={f.rows} disabled={!editable} value={texts[f.key] ?? ""} onChange={(e) => { setTexts({ ...texts, [f.key]: e.target.value }); setSaved(false); }} />
              ) : (
                <input id={f.key} disabled={!editable} value={texts[f.key] ?? ""} onChange={(e) => { setTexts({ ...texts, [f.key]: e.target.value }); setSaved(false); }} />
              )}
              {f.help && <p className="help">{f.help}</p>}
              {f.key === "recommendations" && editable && draft && (
                <button className="btn secondary" style={{ marginTop: 6 }} onClick={() => { setTexts({ ...texts, recommendations: draft }); setSaved(false); }}>
                  Generate automatically
                </button>
              )}
            </div>
          ))}
          {hasFarm && (
            <div className="farm-fields">
              <h3>Farm recommendations (under the legend of every map)</h3>
              <p className="help">Keep each to about 230 characters so it fits the map panel; longer text is shrunk to fit.</p>
              {FARM_FIELDS.map((f) => (
                <div className="field" key={f.key}>
                  <label htmlFor={f.key}>{f.label}</label>
                  <textarea
                    id={f.key}
                    rows={3}
                    maxLength={400}
                    disabled={!editable}
                    value={texts[f.key] ?? ""}
                    onChange={(e) => {
                      setTexts({ ...texts, [f.key]: e.target.value });
                      setSaved(false);
                    }}
                  />
                  <p className="help">
                    {(texts[f.key] ?? "").length} characters
                    {editable && cropDraft[f.crop] && (
                      <>
                        {" · "}
                        <button
                          type="button"
                          className="linklike"
                          onClick={() => {
                            setTexts({ ...texts, [f.key]: cropDraft[f.crop] });
                            setSaved(false);
                          }}
                        >
                          Generate automatically
                        </button>
                      </>
                    )}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
        {editable && (
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn" disabled={!!busy || saved} onClick={saveTexts}>
              {saved ? "Saved" : busy === "save" ? "Saving…" : live ? "Save – update the dashboard" : "Save text"}
            </button>
          </div>
        )}
      </section>

      <section>
        <h2>Exports</h2>
        <p className="muted small">
          For every map: a print-ready PNG (400 dpi) and a PDF, plus one ZIP with all of them
          {version.type === "envi" ? "; for ENVI also the presentation (5760×3240) and the A4 poster (450 dpi), each as PNG and PDF" : ""}. About 12 seconds per
          map.
        </p>
        {canOverlay && editable && (
          <div className="overlay-pick">
            <h3>Standing crops on the maps (optional)</h3>
            {cropInfo?.crops?.length ? (
              <>
                <p className="help">
                  Tick the crops to draw as proportional circles on the maps{version.type === "envi" ? ", the presentation and the poster" : ""},
                  with a circle legend{" "}
                  (standing area as of {cropInfo.as_of}). Then generate or regenerate the exports.
                </p>
                <div className="row">
                  {cropInfo.crops.map((c) => (
                    <label key={c} className="check">
                      <input
                        type="checkbox"
                        checked={cropList.includes(c)}
                        onChange={() => setCropList(cropList.includes(c) ? cropList.filter((x) => x !== c) : [...cropList, c])}
                      />
                      <span className="dot" style={{ background: cropInfo.colors?.[c] }} aria-hidden />
                      {c}
                    </label>
                  ))}
                </div>
              </>
            ) : (
              <p className="help">Upload a standing crops table on the Reference data page first.</p>
            )}
          </div>
        )}
        {stale && (
          <p className="msg warn">
            The text was changed after these files were made: the images and PDFs still show the old text. Regenerate the exports.
          </p>
        )}
        {editable && (
          <button className="btn" disabled={!!busy || (job && !["done", "error"].includes(job.status))} onClick={exportNow}>
            {job && !["done", "error"].includes(job.status) ? "Generating…" : downloads.length ? "Regenerate exports" : "Generate exports"}
          </button>
        )}
        {job && (
          <ul className="progress">
            {lastSteps.slice(-6).map((p, i) => (
              <li key={i} className={p.state === "running" && i === lastSteps.slice(-6).length - 1 && job.status !== "done" ? "running" : ""}>
                {p.message || p.step}
              </li>
            ))}
            {job.status === "error" && <li className="msg err">{job.error}</li>}
          </ul>
        )}
        {job?.status === "done" && (
          <p className={`msg ${job.labels_ok ? "ok" : "warn"}`}>
            {job.labels_ok ? "Label check passed: all 77 municipality and 6 province names placed, 0 overlaps." : "Label check: see label_report.json in the ZIP."}
          </p>
        )}
        {downloads.length > 0 && (
          <Downloads items={downloads} currentLayer={layer?.id} />
        )}
      </section>

      <section>
        <h2>Publish</h2>
        {role !== "admin" ? (
          <p className="muted">An administrator reviews and publishes this version.</p>
        ) : version.status === "draft" ? (
          <>
            <button className="btn" disabled={!!busy || !downloads.length || !saved} onClick={publish}>
              Publish to dashboard
            </button>
            {!downloads.length && <p className="help">Generate the exports first.</p>}
          </>
        ) : version.status === "published" ? (
          <button className="btn secondary" disabled={!!busy} onClick={unpublish}>
            Unpublish
          </button>
        ) : (
          <p className="muted">Archived – no longer on the dashboard.</p>
        )}
        {role === "admin" && version.status !== "published" && (
          <div className="danger-zone">
            <h3>Delete this version</h3>
            <p className="help">Removes this {version.status} version and its maps permanently. Published versions must be unpublished first.</p>
            <DeleteVersionButton id={version.id} label={`version ${version.version} (${version.status})`} />
          </div>
        )}
      </section>
    </main>
  );
}
