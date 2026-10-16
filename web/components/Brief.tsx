"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CatalogEntry, CropsLayer, Gazetteer, Layer, Payload, ProductType } from "@/lib/types";
import { PRODUCT_TYPES } from "@/lib/types";
import { defaultLayer, fmtDate, fmtNumber, fmtValue, irrigationTypes, latestOf, sortIssues, withoutTotals } from "@/lib/format";
import { changeMeaning, classChanges, compareLayerId, enviParts, layerBreaks, type Change, type TrendPoint } from "@/lib/insights";
import { EnviBar, Trends } from "./Insights";

const AT_RISK = ["High", "Very High"];
const MM = 96 / 25.4; // CSS px per mm
const PAGE_H = 283 * MM; // A4 height inside the 7 mm top / bottom page margins
const MIN_ZOOM = 0.75;

const ENVI_ROWS: [string, string, (v: number) => string][] = [
  ["hazard_raw", "Drought forecast score", (v) => fmtNumber(v, 0)],
  ["damage_raw", "Past El Niño damage (mean)", (v) => `${fmtNumber(v)} ha/yr`],
  ["crops_raw", "Standing crops", (v) => `${fmtNumber(v)} ha`],
  ["crop_hvc", "of which high-value crops", (v) => `${fmtNumber(v)} ha`],
  ["livestock_heads", "Livestock & poultry", (v) => `${fmtNumber(v, 0)} heads`],
  ["rank", "Rank in CAR (1 = most vulnerable)", (v) => `#${v} of 77`],
];

const norm = (s: string) => s.toLowerCase().replace(/^city of\s+/, "").replace(/\s+city$/, "").replace(/[^a-z]/g, "");

/** Recommendation lines that name the place (municipality and/or province). */
function localLines(text: string, words: string[]): string[] {
  const ws = words.filter(Boolean).map((w) => w.replace(/ City$/, "").toLowerCase());
  return text.split("\n").map((l) => l.trim()).filter((l) => l && ws.some((w) => l.toLowerCase().includes(w)));
}

function cleanLine(l: string) {
  return l.replace(/^\s*[-•]\s*/, "");
}

/** Cut a long line at a word boundary so the brief stays on one page. */
function shorten(l: string, max: number) {
  return l.length <= max ? l : `${l.slice(0, l.lastIndexOf(" ", max)).replace(/[,;:–-]\s*$/, "")} …`;
}

// --------------------------------------------------------------- map ---

type Geo = { type: string; features: { properties: any; geometry: { type: string; coordinates: any } }[] };

function rings(g: { type: string; coordinates: any }): number[][][] {
  return g.type === "Polygon" ? g.coordinates : g.type === "MultiPolygon" ? g.coordinates.flat() : [];
}

/** The province's municipalities in the map colours; the brief's municipality outlined. */
function BriefMap({ shapes, province, focus, layer }: { shapes: Geo; province: string; focus?: string; layer: Layer }) {
  const feats = shapes.features.filter((f) => f.properties.province === province);
  if (!feats.length) return null;
  const pts = feats.flatMap((f) => rings(f.geometry).flat());
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const k = Math.cos((((y0 + y1) / 2) * Math.PI) / 180);
  const W = 300;
  const H = Math.min(340, (W * (y1 - y0)) / ((x1 - x0) * k));
  const s = Math.min(W / ((x1 - x0) * k), H / (y1 - y0));
  const ox = (W - (x1 - x0) * k * s) / 2;
  const oy = (H - (y1 - y0) * s) / 2;
  const d = (g: any) =>
    rings(g)
      .map((r) => "M" + r.map(([x, y]) => `${(ox + (x - x0) * k * s).toFixed(1)},${(oy + (y1 - y) * s).toFixed(1)}`).join("L") + "Z")
      .join("");
  const target = feats.find((f) => f.properties.area_key === focus);
  return (
    <svg className="brief-map" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Map of ${province}`}>
      {feats.map((f) => {
        const v = layer.values[f.properties.area_key];
        return <path key={f.properties.area_key} d={d(f.geometry)} fill={v?.color ?? "#d9d9d9"} stroke="#555" strokeWidth={0.5} />;
      })}
      {target && <path d={d(target.geometry)} fill="none" stroke="#000" strokeWidth={2.6} />}
    </svg>
  );
}

// ------------------------------------------------------------- brief ---

export default function Brief({ geo, productId, layerId, area, province: provParam }: {
  geo: Gazetteer;
  productId?: string;
  layerId?: string;
  area?: string;
  province?: string;
}) {
  const [catalog, setCatalog] = useState<CatalogEntry[] | null>(null);
  const [payload, setPayload] = useState<Payload | null>(null);
  const [prev, setPrev] = useState<Payload | null>(null);
  const [crops, setCrops] = useState<CropsLayer | null>(null);
  const [irr, setIrr] = useState<any>(null);
  const [shapes, setShapes] = useState<Geo | null>(null);
  const [history, setHistory] = useState<Partial<Record<ProductType, TrendPoint[]>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  // the sheet on screen is laid out as printed: measure it and scale the print down when it is taller than a page
  const sheet = useRef<HTMLElement>(null);
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    const el = sheet.current;
    if (!el) return;
    const fit = () => {
      const first = el.firstElementChild?.getBoundingClientRect();
      const last = el.lastElementChild?.getBoundingClientRect();
      if (!first || !last || el.getBoundingClientRect().width < 200 * MM) return setZoom(1); // phone layout: not measurable
      const h = last.bottom - first.top;
      setZoom(h > PAGE_H ? Math.max(MIN_ZOOM, Math.floor((PAGE_H / h) * 100) / 100) : 1);
    };
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    fit();
    return () => ro.disconnect();
  });

  const g = geo.gazetteer.find((x) => x.area_key === area);
  const province = g?.province ?? provParam ?? "";
  const isProvince = !g;
  const place = g ? g.name : province;

  const json = (url: string) => fetch(url).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${url}: HTTP ${r.status}`))));
  useEffect(() => {
    json("/api/public/catalog").then((d) => setCatalog(d.products)).catch((e) => setError(String(e.message)));
    json("/api/public/crops").then((c) => c?.crops?.length && setCrops(c)).catch(() => undefined);
    json("/api/public/irrigation").then(setIrr).catch(() => undefined);
    json("/geo/municipalities.geojson").then(setShapes).catch(() => undefined);
    if (area) json(`/api/public/history?area=${encodeURIComponent(area)}`).then((d) => setHistory(d.series ?? {})).catch(() => setHistory({}));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [area]);

  const entry = useMemo(() => (catalog ? catalog.find((p) => p.id === productId) ?? latestOf(catalog, "envi") ?? catalog[0] : undefined), [catalog, productId]);
  const prevEntry = useMemo(() => {
    if (!catalog || !entry) return undefined;
    const issues = sortIssues(catalog.filter((p) => p.type === entry.type));
    return issues[issues.findIndex((p) => p.id === entry.id) + 1];
  }, [catalog, entry]);
  useEffect(() => {
    if (!entry) return;
    json(`/api/public/products/${encodeURIComponent(entry.id)}`).then((p) => setPayload(withoutTotals({ ...p, id: entry.id }))).catch((e) => setError(String(e.message)));
  }, [entry?.id]);
  useEffect(() => {
    if (prevEntry) json(`/api/public/products/${encodeURIComponent(prevEntry.id)}`).then(setPrev).catch(() => setPrev(null));
  }, [prevEntry?.id]);

  const layer = payload ? payload.layers.find((l) => l.id === layerId) ?? payload.layers.find((l) => l.id === defaultLayer(payload.type, payload.layers)) ?? payload.layers[0] : null;
  const cmpId = payload && prev ? compareLayerId(payload, layer?.id, prev) : null;
  const changes = useMemo(() => {
    const a = cmpId && payload?.layers.find((l) => l.id === cmpId);
    const b = cmpId && prev?.layers.find((l) => l.id === cmpId);
    return a && b ? classChanges(a, b) : null;
  }, [payload, prev, cmpId]);

  if (error) return <main className="page"><p className="error">{error}</p></main>;
  if (!g && !provParam) return <main className="page"><p className="error">Choose a municipality or a province from the map first.</p><Link href="/">← Back to the map</Link></main>;
  if (!payload || !layer || !catalog) return <main className="page"><p className="muted">Preparing the brief…</p></main>;

  const muni = geo.gazetteer.filter((x) => x.province === province);
  const m = changeMeaning(payload.type);
  const typeLabel = PRODUCT_TYPES.find((t) => t.id === payload.type)?.label ?? payload.title;
  const recs = layer.recommendations ?? payload.texts.recommendations ?? ""; // ENVI month: its own
  const local = localLines(recs, isProvince ? [province] : [place, province]);
  // the numbered CAR-wide actions not already shown for the place (other provinces' bullets are left to the online map)
  const actions = recs.split("\n").map((l) => l.trim()).filter((l) => /^\d+\./.test(l) && !local.includes(l)).slice(0, 7);
  const isEnvi = payload.type === "envi";
  const issueLine = `${payload.period.label} · as of ${fmtDate(payload.issued)}`;

  // irrigation in the place
  const irrFeats: any[] = (irr?.features ?? []).filter((f: any) => {
    const p = f.properties ?? {};
    if (p.province && norm(p.province) !== norm(province)) return false;
    return isProvince ? norm(p.province ?? "") === norm(province) : norm(p.municipality ?? "") === norm(place);
  });
  const irrTypes = Object.fromEntries(irrigationTypes(irr).map((t) => [t.code, t]));

  // standing crops
  const cropsOf = (k: string) => (crops ? crops.crops.map((c) => [c, crops.values[k]?.[c] ?? 0] as [string, number]).filter(([, ha]) => ha > 0) : []);
  const keys = isProvince ? muni.map((x) => x.area_key) : [area!];
  const cropTotals: Record<string, number> = {};
  const cropRisk: Record<string, number> = {};
  for (const k of keys)
    for (const [c, ha] of cropsOf(k)) {
      cropTotals[c] = (cropTotals[c] ?? 0) + ha;
      if (isEnvi && AT_RISK.includes(layer.values[k]?.class)) cropRisk[c] = (cropRisk[c] ?? 0) + ha;
    }

  return (
    <div className="brief-wrap">
      <div className="brief-tools no-print">
        <Link href="/">← Back to the map</Link>
        <span className="muted">Tip: in the print dialog choose “Save as PDF”, paper A4, margins default.</span>
        {zoom < 1 && <span className="brief-fit">Printed at {Math.round(zoom * 100)}% to fit one A4 page.</span>}
        <button className="btn" onClick={() => window.print()}>🖨 Print / Save as PDF</button>
      </div>

      <article className="brief" ref={sheet} style={{ "--print-zoom": zoom } as React.CSSProperties}>
        <header className="brief-head">
          <div className="brief-logos">
            <img src="/logos/da-car.webp" alt="DA-RFO-CAR" width={40} height={40} />
            <img src="/logos/amia.webp" alt="AMIA" width={40} height={40} />
          </div>
          <div>
            <div className="brief-kicker">{isProvince ? "Provincial" : "Municipal"} climate-risk brief · DA-RFO-CAR AMIA Program</div>
            <h1>{isProvince ? province : `${place}, ${province}`}</h1>
            <div className="brief-sub">{typeLabel} · {layer.label} · {issueLine}</div>
          </div>
        </header>

        <section className="brief-top">
          {shapes && <BriefMap shapes={shapes} province={province} focus={g?.area_key} layer={layer} />}
          <div className="brief-status">
            {isProvince ? (
              <ProvinceStatus layer={layer} keys={keys} changes={changes} m={m} isEnvi={isEnvi} />
            ) : (
              <MuniStatus payload={payload} layer={layer} areaKey={area!} change={changes?.[area!]} hasPrev={!!cmpId} m={m} prevLabel={prevEntry?.period.label} />
            )}
            <ul className="brief-legend">
              {layer.legend.classes.map((c) => (
                <li key={c.label}><span className="sw" style={{ background: c.color }} />{c.label}{layer.unit === "mm" && layer.legend.kind === "graduated" ? " mm" : ""}</li>
              ))}
            </ul>
          </div>
        </section>

        {isProvince && (
          <section className="brief-sec">
            <h2>Municipalities</h2>
            <MuniTable layer={layer} muni={muni} changes={changes} m={m} crops={crops} />
          </section>
        )}

        {!isProvince && <MuniDetails payload={payload} layer={layer} areaKey={area!} name={place} />}

        <div className="brief-cols">
          <section className="brief-sec">
            <h2>Standing crops {crops && <span className="muted">(as of {crops.as_of})</span>}</h2>
            {Object.keys(cropTotals).length ? (
              <table className="brief-table">
                <thead><tr><th>Crop</th><th>Standing (ha)</th>{isEnvi && <th>At risk* (ha)</th>}</tr></thead>
                <tbody>
                  {Object.entries(cropTotals).sort((a, b) => b[1] - a[1]).map(([c, ha]) => (
                    <tr key={c}><td>{c}</td><td>{fmtNumber(ha, 0)}</td>{isEnvi && <td>{fmtNumber(cropRisk[c] ?? 0, 0)}</td>}</tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="muted">No standing crops recorded.</p>}
            {isEnvi && <p className="brief-note">*In municipalities classed High or Very High.</p>}
          </section>
          <section className="brief-sec">
            <h2>Irrigation sources &amp; dams</h2>
            {irrFeats.length ? (
              <table className="brief-table">
                <thead><tr><th>Name</th><th>Type</th>{isProvince && <th>Municipality</th>}<th>Service area</th></tr></thead>
                <tbody>
                  {[...irrFeats].sort((a, b) => (Number(b.properties.service_area_ha) || 0) - (Number(a.properties.service_area_ha) || 0)).slice(0, 8).map((f, i) => (
                    <tr key={i}>
                      <td>{f.properties.name}</td>
                      <td>{f.properties.type}</td>
                      {isProvince && <td>{f.properties.municipality}</td>}
                      <td>{f.properties.service_area_ha ? `${fmtNumber(Number(f.properties.service_area_ha), 0)} ha` : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="muted">No irrigation sources or dams recorded {isProvince ? "in the province" : `for ${place}`}.</p>}
            {irrFeats.length > 8 && <p className="brief-note">+{irrFeats.length - 8} more on the online map.</p>}
            {irrFeats.length > 0 && (
              <p className="brief-note">
                {Object.entries(irrFeats.reduce((a: Record<string, number>, f: any) => ({ ...a, [f.properties.type]: (a[f.properties.type] ?? 0) + 1 }), {}))
                  .map(([t, n]) => `${n} ${irrTypes[t]?.label ?? t}`).join(" · ")}
              </p>
            )}
          </section>
        </div>

        {!isProvince && (
          <section className="brief-sec">
            <h2>Trend over past issues</h2>
            <Trends series={history} />
          </section>
        )}

        {recs && (
          <section className="brief-sec flow">
            <h2>Recommendations</h2>
            {local.length > 0 && (
              <div className="brief-local">
                <div className="brief-kicker">For {isProvince ? province : `${place} / ${province}`}</div>
                {local.map((l, i) => <p key={i}>{shorten(cleanLine(l), 240)}</p>)}
              </div>
            )}
            {actions.length > 0 && (
              <div className="brief-recs">
                <div className="brief-kicker">CAR-wide actions</div>
                {actions.map((l, i) => <p key={i} className="num">{shorten(l, 130)}</p>)}
                <p className="brief-note">Full recommendations on the online map.</p>
              </div>
            )}
          </section>
        )}

        <footer className="brief-foot">
          <p>
            <strong>Sources:</strong> {payload.texts.sources}. {payload.texts.disclaimer} Generated{" "}
            {fmtDate(new Date().toISOString().slice(0, 10))} from AMIA CAR MAPS (DA-RFO-CAR).
          </p>
        </footer>
      </article>
    </div>
  );
}

function MuniStatus({ payload, layer, areaKey, change, hasPrev, m, prevLabel }: {
  payload: Payload; layer: Layer; areaKey: string; change?: Change; hasPrev: boolean;
  m: ReturnType<typeof changeMeaning>; prevLabel?: string;
}) {
  const v = layer.values[areaKey];
  return (
    <>
      <div className="brief-class" style={{ borderColor: v?.color ?? "#999" }}>
        <span className="sw big" style={{ background: v?.color ?? "#d9d9d9" }} />
        <div>
          <div className="brief-big">{v?.class ?? "No data"}</div>
          <div>
            {payload.type === "envi" && typeof v?.envi === "number"
              ? `ENVI ${v.envi.toFixed(3)}${typeof v.rank === "number" ? ` · rank #${v.rank} of 77` : ""}`
              : fmtValue(v, layer) !== v?.class ? fmtValue(v, layer) : null}
          </div>
        </div>
      </div>
      {hasPrev && (
        <p className="brief-change">
          {change ? (
            <span style={{ color: change.dir > 0 ? m.upColor : m.downColor }}>
              {change.dir > 0 ? "▲ Up" : "▼ Down"} from {change.from} ({change.dir > 0 ? m.up : m.down})
            </span>
          ) : "● No change in class"}{" "}
          since the {prevLabel} issue.
        </p>
      )}
      {!hasPrev && <p className="brief-note">First issue of this map: no earlier issue to compare with.</p>}
    </>
  );
}

function ProvinceStatus({ layer, keys, changes, m, isEnvi }: {
  layer: Layer; keys: string[]; changes: Record<string, Change> | null; m: ReturnType<typeof changeMeaning>; isEnvi: boolean;
}) {
  const counts = layer.legend.classes.map((c) => ({ ...c, n: keys.filter((k) => layer.values[k]?.class === c.label).length }));
  const max = Math.max(1, ...counts.map((c) => c.n));
  const risk = keys.filter((k) => AT_RISK.includes(layer.values[k]?.class)).length;
  const up = keys.filter((k) => changes?.[k]?.dir === 1).length;
  const down = keys.filter((k) => changes?.[k]?.dir === -1).length;
  return (
    <>
      {isEnvi && <div className="brief-big">{risk} of {keys.length} municipalities High or Very High</div>}
      <ul className="bars brief-bars">
        {counts.map((c) => (
          <li key={c.label}>
            <span className="bar-label">{c.label}</span>
            <span className="bar-track"><span className="bar" style={{ width: `${(c.n / max) * 100}%`, background: c.color }} /></span>
            <span className="count">{c.n}</span>
          </li>
        ))}
      </ul>
      {changes && (
        <p className="brief-change">
          Since the last issue: <span style={{ color: m.upColor }}>▲ {up} up</span> · <span style={{ color: m.downColor }}>▼ {down} down</span>
        </p>
      )}
    </>
  );
}

function MuniTable({ layer, muni, changes, m, crops }: {
  layer: Layer; muni: Gazetteer["gazetteer"]; changes: Record<string, Change> | null; m: ReturnType<typeof changeMeaning>; crops: CropsLayer | null;
}) {
  const order = layer.legend.classes.map((c) => c.label);
  const num = (k: string) => {
    const v = layer.values[k];
    return typeof v?.envi === "number" ? v.envi : typeof v?.value === "number" ? v.value : order.indexOf(v?.class ?? "");
  };
  const rows = [...muni].sort((a, b) => num(b.area_key) - num(a.area_key));
  const total = (k: string) => (crops ? Object.values(crops.values[k] ?? {}).reduce((s, x) => s + x, 0) : 0);
  // many municipalities (Abra has 27): two tables side by side, so the province still fits one page
  const two = rows.length > 14;
  const table = (part: typeof rows) => (
    <table className="brief-table brief-muni">
      <thead><tr><th>Municipality</th><th>Class</th><th>Value</th><th>{two ? "Was" : "Change"}</th>{crops && <th>{two ? "Crops" : "Crops (ha)"}</th>}</tr></thead>
      <tbody>
        {part.map((x) => {
          const v = layer.values[x.area_key];
          const c = changes?.[x.area_key];
          return (
            <tr key={x.area_key}>
              <td>{x.name}</td>
              <td><span className="sw" style={{ background: v?.color ?? "#d9d9d9" }} />{v?.class ?? "No data"}</td>
              <td>{typeof v?.envi === "number" ? v.envi.toFixed(2) : fmtValue(v, layer)}</td>
              <td style={{ color: c ? (c.dir > 0 ? m.upColor : m.downColor) : undefined }}>
                {c ? `${c.dir > 0 ? "▲" : "▼"} ${two ? c.from : `from ${c.from}`}` : "–"}
              </td>
              {crops && <td>{fmtNumber(total(x.area_key), 0)}</td>}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
  if (!two) return table(rows);
  const half = Math.ceil(rows.length / 2);
  return (
    <div className="brief-cols brief-muni-two">
      {table(rows.slice(0, half))}
      {table(rows.slice(half))}
    </div>
  );
}

function MuniDetails({ payload, layer, areaKey, name }: { payload: Payload; layer: Layer; areaKey: string; name: string }) {
  const series = payload.layers.filter((l) => /^(d_|m_)/.test(l.id));
  const isEnvi = payload.type === "envi";
  const v = layer.values[areaKey]; // ENVI: the season or one month
  const parts = isEnvi ? enviParts(v, payload.method?.weights) : null;
  return (
    <>
      {isEnvi && v && parts && typeof v.envi === "number" && (
        <section className="brief-sec">
          <h2>Why is it {v.class}{layer.id.startsWith("m_") ? ` in ${layer.label}` : ""}?</h2>
          <div className="brief-cols">
            <EnviBar name={name} cls={v.class} envi={v.envi} parts={parts} breaks={layerBreaks(layer, payload.method?.breaks)} />
            <table className="brief-table">
              <tbody>
                {typeof v.drought_category === "string" && <tr><th>Drought forecast ({layer.label})</th><td>{v.drought_category}</td></tr>}
                {ENVI_ROWS.filter(([k]) => typeof v[k] === "number").map(([k, label, f]) => (
                  <tr key={k}><th>{label}</th><td>{f(v[k] as number)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {series.length > 1 && (
        <section className="brief-sec">
          <h2>{series[0].id.startsWith("d_") ? "Day by day" : isEnvi ? "ENVI month by month" : "Month by month"}</h2>
          <table className="brief-table brief-series">
            <tbody>
              <tr>{series.map((l) => <th key={l.id}>{l.label.replace(/^([A-Z][a-z]{2})[a-z]*/, "$1")}</th>)}</tr>
              <tr>
                {series.map((l) => {
                  const x = l.values[areaKey];
                  return (
                    <td key={l.id} style={{ background: x?.color }} title={x?.class}>
                      {typeof x?.envi === "number" ? x.envi.toFixed(2) : typeof x?.value === "number" ? fmtNumber(x.value, 0) : x?.class ?? "–"}
                    </td>
                  );
                })}
              </tr>
            </tbody>
          </table>
          {layer.unit === "mm" && <p className="brief-note">Rainfall in mm.</p>}
          {isEnvi && <p className="brief-note">Monthly ENVI uses that month's drought forecast (score ÷ 3); colours are the ENVI classes.</p>}
        </section>
      )}
    </>
  );
}
