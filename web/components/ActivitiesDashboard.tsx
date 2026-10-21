"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ACTIVITY_STATUSES, beneficiariesText, coverage, defaultVulnerableClasses, emptyCounts, inAny, placesSummary,
  worstClasses,
  type Activity, type StatusCounts,
} from "@/lib/activities";
import { fmtDate, fmtNumber, sortIssues, withoutTotals } from "@/lib/format";
import { type CatalogEntry, type Gazetteer, type Layer, type Payload, type ProductType } from "@/lib/types";
import { dateRange, StatusChip } from "./ActivityBits";
import TopNav from "./TopNav";

const ALL = "__all__"; // every month / day of the issue: the highest class an area reaches
const GOOD = "#2e7d32";
const BAD = "#d32f2f";
const CALM = "#dfe5e1";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Months / days of an issue (one map each); season and %-of-normal maps are left out of "all". */
const periodLayers = (p: Payload) => p.layers.filter((l) => /^(m|d)_/.test(l.id));

const money = (n: number) =>
  n >= 1e9 ? `₱${fmtNumber(n / 1e9, 1)}B` : n >= 1e6 ? `₱${fmtNumber(n / 1e6, 1)}M` : n >= 1e4 ? `₱${fmtNumber(n / 1e3, 0)}K` : `₱${fmtNumber(n, 0)}`;
const plural = (n: number, one: string, many = `${one}s`) => `${fmtNumber(n, 0)} ${n === 1 ? one : many}`;
const listWords = (xs: string[]) => (xs.length <= 1 ? xs.join("") : `${xs.slice(0, -1).join(", ")} or ${xs[xs.length - 1]}`);

// ------------------------------------------------------------------ icons ---

const PATHS = {
  pin: "M12 2a7 7 0 0 0-7 7c0 5.2 7 13 7 13s7-7.8 7-13a7 7 0 0 0-7-7Zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5Z",
  check: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm-1.4 14.2-4.3-4.3 1.4-1.4 2.9 2.9 6.1-6.1 1.4 1.4-7.5 7.5Z",
  alert: "M12 2 1 21h22L12 2Zm1 15h-2v-2h2v2Zm0-4h-2V9h2v4Z",
  list: "M4 5h2v2H4V5Zm4 0h12v2H8V5ZM4 11h2v2H4v-2Zm4 0h12v2H8v-2Zm-4 6h2v2H4v-2Zm4 0h12v2H8v-2Z",
  people: "M16 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm-8 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm0 2c-2.7 0-8 1.3-8 4v3h10v-3c0-1 .4-1.9 1.1-2.6A13 13 0 0 0 8 13Zm8 0c-.3 0-.6 0-1 .1 1.2.9 2 2 2 3.9v3h7v-3c0-2.7-5.3-4-8-4Z",
  peso: "M7 3h6a6 6 0 0 1 5.9 5H21v2h-2.1a6 6 0 0 1 0 1H21v2h-2.1A6 6 0 0 1 13 17H9v4H7v-8H5v-2h2v-1H5V8h2V3Zm2 2v3h7.8A4 4 0 0 0 13 5H9Zm0 5v1h8a4 4 0 0 0 0-1H9Zm0 3v2h4a4 4 0 0 0 3.8-2H9Z",
};
function Icon({ name, size = 22 }: { name: keyof typeof PATHS; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="currentColor" aria-hidden>
      <path d={PATHS[name]} />
    </svg>
  );
}

// ---------------------------------------------------------------- charts ---

/** Ring: share of the at-risk municipalities that have an activity. */
function Ring({ covered, total, size = 150, light = false }: { covered: number; total: number; size?: number; light?: boolean }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  const share = total ? covered / total : 0;
  return (
    <svg viewBox="0 0 140 140" width={size} height={size} className={`ad-ring${light ? " light" : ""}`} role="img"
      aria-label={`${covered} of ${total} places at risk have an activity`}>
      <circle cx="70" cy="70" r={r} fill="none" className="ad-ring-track" strokeWidth="16" />
      {total > 0 && share > 0 && (
        <circle cx="70" cy="70" r={r} fill="none" className="ad-ring-val" strokeWidth="16" strokeDasharray={`${share * c} ${c}`}
          transform="rotate(-90 70 70)" strokeLinecap="round" />
      )}
      <text x="70" y="70" textAnchor="middle" className="ad-ring-big">{total ? `${Math.round(share * 100)}%` : "–"}</text>
      <text x="70" y="92" textAnchor="middle" className="ad-ring-small">covered</text>
    </svg>
  );
}

/** Horizontal bars with the number at the end. */
function HBars({ items }: { items: { label: string; value: number; color: string; dim?: boolean }[] }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <ul className="ad-hbars">
      {items.map((i) => (
        <li key={i.label} className={i.dim ? "dim" : ""}>
          <span className="ad-hbar-label" title={i.label}>{i.label}</span>
          <span className="ad-hbar-track">
            <span className="ad-hbar" style={{ width: `${(i.value / max) * 100}%`, background: i.color }} />
          </span>
          <span className="ad-hbar-val">{fmtNumber(i.value, 0)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Per province: at-risk municipalities with (green) and without (red) an activity. */
function ProvinceChart({ rows, onPick, picked }: {
  rows: { province: string; covered: number; vulnerable: number }[];
  onPick: (p: string) => void;
  picked: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.vulnerable));
  return (
    <ul className="ad-prov">
      {rows.map((r) => {
        const gap = r.vulnerable - r.covered;
        return (
          <li key={r.province} className={picked && picked !== r.province ? "dim" : ""}>
            <button className="ad-prov-name" onClick={() => onPick(picked === r.province ? "" : r.province)} aria-pressed={picked === r.province}>
              {r.province}
            </button>
            <span className="ad-prov-track">
              {r.vulnerable === 0 ? (
                <span className="ad-prov-zero">none at risk</span>
              ) : (
                <>
                  <span style={{ width: `${(r.covered / max) * 100}%`, background: GOOD }} title={`${r.covered} with an activity`}>
                    {r.covered / max >= 0.08 && r.covered}
                  </span>
                  <span style={{ width: `${(gap / max) * 100}%`, background: BAD }} title={`${gap} without an activity`}>
                    {gap / max >= 0.08 && gap}
                  </span>
                </>
              )}
            </span>
            <span className="ad-prov-total">{r.vulnerable ? `${r.covered}/${r.vulnerable}` : ""}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** Activities per month of their start date, stacked by status. */
function MonthChart({ acts }: { acts: Activity[] }) {
  const dated = acts.filter((a) => a.start_date);
  if (!dated.length) return <p className="ad-empty">No activity has a start date yet.</p>;
  const keys = [...new Set(dated.map((a) => a.start_date!.slice(0, 7)))].sort();
  const months: string[] = [];
  let [y, m] = keys[0].split("-").map(Number);
  const last = keys[keys.length - 1];
  while (`${y}-${String(m).padStart(2, "0")}` <= last) {
    months.push(`${y}-${String(m).padStart(2, "0")}`);
    m += 1;
    if (m > 12) [y, m] = [y + 1, 1];
  }
  const shown = months.slice(-12);
  const by = new Map(shown.map((k) => [k, emptyCounts()]));
  for (const a of dated) {
    const c = by.get(a.start_date!.slice(0, 7));
    if (c) c[a.status] += 1;
  }
  const tot = (c: StatusCounts) => ACTIVITY_STATUSES.reduce((s, x) => s + c[x.id], 0);
  const max = Math.max(1, ...[...by.values()].map(tot));
  const now = new Date().toISOString().slice(0, 7);
  return (
    <div className="ad-cols" role="img" aria-label="Activities by the month they start">
      {shown.map((k) => {
        const c = by.get(k)!;
        const [yy, mm] = k.split("-").map(Number);
        return (
          <div key={k} className={`ad-col${k === now ? " now" : ""}`}>
            <span className="ad-col-n">{tot(c) || ""}</span>
            <span className="ad-col-area">
              <span className="ad-col-bar" style={{ height: `${(tot(c) / max) * 100}%` }}>
                {ACTIVITY_STATUSES.map((s) => (c[s.id] ? <span key={s.id} style={{ flexGrow: c[s.id], background: s.color }} /> : null))}
              </span>
            </span>
            <span className="ad-col-lab">
              {k === now ? "This month" : MONTHS[mm - 1]}
              {k !== now && (mm === 1 || k === shown[0]) && <small> {yy}</small>}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function StatusKey() {
  return (
    <ul className="ad-key">
      {ACTIVITY_STATUSES.map((s) => (
        <li key={s.id}>
          <i style={{ background: s.color }} aria-hidden /> {s.label}
        </li>
      ))}
    </ul>
  );
}

function ClassDot({ label, color }: { label: string; color: string }) {
  return (
    <span className="ad-class">
      <i style={{ background: color }} aria-hidden />
      {label}
    </span>
  );
}

// ------------------------------------------------------------ coverage map ---

type Geo = { type: string; features: { properties: Record<string, any>; geometry: { type: string; coordinates: any } }[] };

/** CAR municipalities as SVG: green = at risk with an activity, red = at risk without, grey = not at risk. */
function CoverageMap({ state, names, onPick }: {
  state: Record<string, "ok" | "bad" | "calm">;
  names: Map<string, { name: string; province: string }>;
  onPick: (k: string) => void;
}) {
  const [geo, setGeo] = useState<{ muni: Geo; prov: Geo } | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([fetch("/geo/municipalities.geojson").then((r) => r.json()), fetch("/geo/provinces.geojson").then((r) => r.json())])
      .then(([muni, prov]) => setGeo({ muni, prov }))
      .catch(() => setGeo(null));
  }, []);
  const view = useMemo(() => {
    if (!geo) return null;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const rings = (g: Geo["features"][0]["geometry"]): number[][][] => (g.type === "Polygon" ? g.coordinates : g.coordinates.flat());
    for (const f of geo.muni.features) for (const ring of rings(f.geometry)) for (const [x, y] of ring) {
      x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
    }
    const k = Math.cos(((y0 + y1) / 2) * (Math.PI / 180));
    const W = 1000;
    const s = W / ((x1 - x0) * k);
    const H = (y1 - y0) * s;
    const path = (g: Geo["features"][0]["geometry"]) =>
      rings(g).map((ring) => "M" + ring.map(([x, y]) => `${((x - x0) * k * s).toFixed(1)},${((y1 - y) * s).toFixed(1)}`).join("L") + "Z").join("");
    return {
      W, H,
      muni: geo.muni.features.map((f) => ({ key: f.properties.area_key as string, d: path(f.geometry) })),
      prov: geo.prov.features.map((f, i) => ({ key: String(i), d: path(f.geometry) })),
    };
  }, [geo]);
  if (!view) return <div className="ad-map-loading">Loading map…</div>;
  const h = hover ? names.get(hover) : null;
  const fill = (k: string) => (state[k] === "ok" ? GOOD : state[k] === "bad" ? BAD : CALM);
  return (
    <div className="ad-map">
      <svg viewBox={`-6 -6 ${view.W + 12} ${view.H + 12}`} role="img" aria-label="Map of the municipalities: green with an activity, red needs attention">
        {view.muni.map((m) => (
          <path key={m.key} d={m.d} fill={fill(m.key)} className={`ad-map-area${hover === m.key ? " hover" : ""}`}
            onMouseEnter={() => setHover(m.key)} onMouseLeave={() => setHover(null)} onClick={() => onPick(m.key)}>
            <title>{names.get(m.key)?.name}</title>
          </path>
        ))}
        {view.prov.map((p) => <path key={p.key} d={p.d} className="ad-map-prov" />)}
      </svg>
      <div className={`ad-map-tip${h ? " on" : ""}`} aria-hidden>
        {h && (
          <>
            <strong>{h.name}</strong> <span>{h.province}</span>
            <em className={state[hover!] ?? "calm"}>
              {state[hover!] === "ok" ? "Has an activity" : state[hover!] === "bad" ? "Needs attention" : "Not at risk"}
            </em>
          </>
        )}
      </div>
      <ul className="ad-key">
        <li><i style={{ background: GOOD }} /> At risk, has an activity</li>
        <li><i style={{ background: BAD }} /> At risk, no activity yet</li>
        <li><i style={{ background: CALM }} /> Not at risk</li>
      </ul>
    </div>
  );
}

// ------------------------------------------------------------------ page ---

type View = "risk" | "gaps" | "covered" | "all";

export default function ActivitiesDashboard({ geo }: { geo: Gazetteer }) {
  const [catalog, setCatalog] = useState<CatalogEntry[] | null>(null);
  const [acts, setActs] = useState<Activity[] | null>(null);
  const type: ProductType = "envi"; // the El Niño Action Plan follows the El Niño Vulnerability Index only
  const [productId, setProductId] = useState<string | null>(null);
  const [payload, setPayload] = useState<Payload | null>(null);
  const [layerId, setLayerId] = useState<string | null>(null);
  const [classes, setClasses] = useState<string[] | null>(null);
  const [view, setView] = useState<View>("risk");
  const [prov, setProv] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [help, setHelp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLElement>(null);

  useEffect(() => {
    fetch("/api/public/catalog")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`Catalog: HTTP ${r.status}`))))
      .then((d) => setCatalog(d.products))
      .catch((e) => setError(String(e.message ?? e)));
    fetch("/api/public/activities")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`Activities: HTTP ${r.status}`))))
      .then((d) => setActs(d.activities))
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  const issues = useMemo(() => sortIssues((catalog ?? []).filter((p) => p.type === type)), [catalog, type]);
  const entry = issues.find((p) => p.id === productId) ?? issues[0];

  useEffect(() => {
    if (!entry) return;
    let cancelled = false;
    setPayload(null);
    fetch(`/api/public/products/${encodeURIComponent(entry.id)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`Map: HTTP ${r.status}`))))
      .then((p: Payload) => {
        if (cancelled) return;
        const pl = withoutTotals({ ...p, id: entry.id });
        setPayload(pl);
        setLayerId(pl.layers[0]?.id ?? null);   // the whole-season ENVI
        setClasses(null);
      })
      .catch((e) => !cancelled && setError(String(e.message ?? e)));
    return () => {
      cancelled = true;
    };
  }, [entry?.id]);

  const layers: Layer[] = useMemo(() => {
    if (!payload) return [];
    if (layerId === ALL) return periodLayers(payload);
    const l = payload.layers.find((x) => x.id === layerId) ?? payload.layers[0];
    return l ? [l] : [];
  }, [payload, layerId]);
  const legend = layers[0]?.legend;
  const chosen = classes ?? (layers[0] ? defaultVulnerableClasses(layers[0]) : []);
  const chosenKey = chosen.join("|");
  const byArea = useMemo(() => worstClasses(layers), [layers]);
  const byKey = useMemo(() => new Map(geo.gazetteer.map((g) => [g.area_key, g])), [geo]);
  const provinces = useMemo(() => [...new Set(geo.gazetteer.map((g) => g.province))].sort(), [geo]);
  const className = (c: string) => legend?.classes.find((x) => x.label === c)?.desc ?? c;

  const classCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const [k, v] of Object.entries(byArea)) if (!prov || byKey.get(k)?.province === prov) c[v.class] = (c[v.class] ?? 0) + 1;
    return c;
  }, [byArea, prov, byKey]);
  // every at-risk municipality in CAR (the map and the province chart), and those of the chosen province
  const allRisk = useMemo(
    () => Object.entries(byArea).filter(([, v]) => chosen.includes(v.class)).map(([k]) => k),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [byArea, chosenKey],
  );
  const vulnerable = useMemo(
    () =>
      allRisk
        .filter((k) => !prov || byKey.get(k)?.province === prov)
        .sort((a, b) => byArea[b].rank - byArea[a].rank || (byKey.get(a)?.name ?? "").localeCompare(byKey.get(b)?.name ?? "")),
    [allRisk, prov, byKey, byArea],
  );
  const relevant = useMemo(() => acts ?? [], [acts]);
  const cov = useMemo(() => coverage(vulnerable, relevant), [vulnerable, relevant]);
  const atRiskActs = useMemo(() => {
    const set = new Set(vulnerable);
    return relevant.filter((a) => inAny(a, set));
  }, [vulnerable, relevant]);
  const actsByArea = useMemo(() => {
    const m = new Map<string, Activity[]>();
    for (const a of relevant) for (const k of a.area_keys) m.set(k, [...(m.get(k) ?? []), a]);
    return m;
  }, [relevant]);
  const mapState = useMemo(() => {
    const out: Record<string, "ok" | "bad" | "calm"> = {};
    const all = coverage(allRisk, relevant);
    const gaps = new Set(all.gaps);
    for (const k of allRisk) out[k] = gaps.has(k) ? "bad" : "ok";
    return out;
  }, [allRisk, relevant]);
  const perProvince = useMemo(
    () => provinces.map((p) => ({ province: p, ...coverage(allRisk.filter((k) => byKey.get(k)?.province === p), relevant) })),
    [provinces, allRisk, relevant, byKey],
  );
  const categories = useMemo(() => {
    const c = new Map<string, number>();
    for (const a of atRiskActs) c.set(a.category || "Other", (c.get(a.category || "Other") ?? 0) + 1);
    return [...c.entries()].sort((a, b) => b[1] - a[1]).slice(0, 7);
  }, [atRiskActs]);

  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const gaps = new Set(cov.gaps);
    const keys =
      view === "all"
        ? geo.gazetteer.map((g) => g.area_key).filter((k) => !prov || byKey.get(k)?.province === prov).sort(
            (a, b) => (byArea[b]?.rank ?? -1) - (byArea[a]?.rank ?? -1) || (byKey.get(a)?.name ?? "").localeCompare(byKey.get(b)?.name ?? ""),
          )
        : vulnerable.filter((k) => (view === "gaps" ? gaps.has(k) : view === "covered" ? !gaps.has(k) : true));
    const risk = new Set(vulnerable);
    return keys
      .filter((k) => !s || byKey.get(k)?.name.toLowerCase().includes(s) || (actsByArea.get(k) ?? []).some((a) => a.title.toLowerCase().includes(s)))
      .map((k) => ({ key: k, atRisk: risk.has(k), gap: gaps.has(k) }));
  }, [view, vulnerable, cov.gaps, geo, byArea, byKey, prov, q, actsByArea]);

  const pickArea = (k: string) => {
    const g = byKey.get(k);
    if (prov && g?.province !== prov) setProv("");
    setView(mapState[k] ? "risk" : "all");
    setQ("");
    setOpen(k);
    setTimeout(() => document.getElementById(`area-${k}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 60);
  };

  const loading = !error && (catalog === null || acts === null || (entry && !payload));
  const total = ACTIVITY_STATUSES.reduce((s, x) => s + cov.counts[x.id], 0);
  const where = prov ? ` in ${prov}` : "";
  const mapsHref = `/?type=envi${entry ? `&p=${encodeURIComponent(entry.id)}` : ""}`;
  const towns = prov ? geo.gazetteer.filter((g) => g.province === prov).length : geo.gazetteer.length;
  const pct = cov.vulnerable ? Math.round((cov.covered / cov.vulnerable) * 100) : 0;

  return (
    <div className="ad">
      <header className="topbar">
        <div className="logos">
          <img src="/logos/da-car.webp" alt="Department of Agriculture – Cordillera Administrative Region" width={44} height={44} />
          <img src="/logos/bagong-pilipinas.webp" alt="Bagong Pilipinas" width={47} height={44} />
          <img src="/logos/amia.webp" alt="AMIA – Adaptation and Mitigation Initiative in Agriculture" width={44} height={44} />
        </div>
        <div className="titles">
          <h1>El Niño Action Plan Dashboard</h1>
          <p>DA-RFO-CAR · AMIA Program</p>
        </div>
        <TopNav active="activities" mapsHref={mapsHref} />
        <button className="guide-btn" onClick={() => setHelp((h) => !h)} aria-expanded={help} aria-label="How to read this page">
          <span aria-hidden>?</span>
          <span className="guide-label">How to read</span>
        </button>
      </header>

      <main className="ad-main">
        {help && (
          <section className="ad-help">
            <h2>How to read this page</h2>
            <ol>
              <li>The page follows the latest <strong>El Niño Vulnerability Index (ENVI)</strong> map and finds the municipalities
                that are <strong>at risk</strong> (High or Very High vulnerability).</li>
              <li><strong>Green</strong> places already have an activity of the Department of Agriculture (to conduct, ongoing or done).
                <strong> Red</strong> places are at risk but have no activity yet – they need attention first.</li>
              <li><strong>Tap a place</strong> on the map or in the list to see its activities. Tap a <strong>province</strong> to see only its places.</li>
              <li>“At risk” follows the map colours shown under <em>Counting as at risk</em>; tap <em>Change</em> to choose others.</li>
            </ol>
            <button className="btn" onClick={() => setHelp(false)}>Got it</button>
          </section>
        )}
        {error && <p className="error">{error}</p>}

        <section className="ad-hero">
          <div className="ad-hero-text">
            <p className="ad-kicker">El Niño Action Plan · El Niño Vulnerability Index (ENVI)</p>
            {payload && acts ? (
              <h2 className="ad-headline">
                {cov.vulnerable === 0 ? (
                  <>No municipality{where} is at risk on this map.</>
                ) : (
                  <>
                    <b>{plural(cov.vulnerable, "municipality", "municipalities")}</b>{where} {cov.vulnerable === 1 ? "has" : "have"} high El Niño vulnerability.{" "}
                    <span className="ok">{fmtNumber(cov.covered, 0)} {cov.covered === 1 ? "has" : "have"} an activity</span>
                    {cov.gaps.length > 0 ? (
                      <>, <span className="bad">{fmtNumber(cov.gaps.length, 0)} still {cov.gaps.length === 1 ? "needs" : "need"} one</span>.</>
                    ) : (
                      <> – every one is covered.</>
                    )}
                  </>
                )}
              </h2>
            ) : (
              <h2 className="ad-headline">{loading ? "Loading…" : "No El Niño Vulnerability Index (ENVI) map has been published yet."}</h2>
            )}
            {payload && (
              <div className="ad-hero-meta">
                <span className="ad-chip">{payload.period.label}</span>
                <span className="ad-chip">as of {fmtDate(payload.issued)}</span>
                {issues.length > 1 && (
                  <select value={entry?.id} onChange={(e) => setProductId(e.target.value)} aria-label="Issue">
                    {issues.map((p) => (
                      <option key={p.id} value={p.id}>Issue: {p.period.label}</option>
                    ))}
                  </select>
                )}
                {payload.layers.length > 1 && (
                  <select value={layerId ?? ""} onChange={(e) => { setLayerId(e.target.value); setClasses(null); }} aria-label="Period">
                    {periodLayers(payload).length > 1 && payload.type !== "envi" && (
                      <option value={ALL}>Worst {payload.type === "rainfall_dekad" ? "day" : "month"} of the outlook</option>
                    )}
                    {payload.layers.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
                    {periodLayers(payload).length > 1 && payload.type === "envi" && (
                      <option value={ALL}>Worst month of the outlook</option>
                    )}
                  </select>
                )}
              </div>
            )}
          </div>
          {payload && acts && (
            <div className="ad-hero-ring">
              <Ring covered={cov.covered} total={cov.vulnerable} light />
              <span>{cov.covered} of {cov.vulnerable} places at risk<br />have an activity</span>
            </div>
          )}
        </section>

        {legend && (
          <details className="ad-count-as">
            <summary>
              <span className="ad-count-label">Counting as at risk:</span>
              {chosen.length ? chosen.map((c) => (
                <span key={c} className="ad-pill">
                  <i style={{ background: legend.classes.find((x) => x.label === c)?.color }} /> {className(c)}
                </span>
              )) : <span className="ad-pill">nothing chosen</span>}
              <span className="ad-change">Change</span>
            </summary>
            <div className="ad-classes">
              {legend.classes.map((c) => {
                const on = chosen.includes(c.label);
                return (
                  <button key={c.label} className={on ? "on" : ""} aria-pressed={on}
                    onClick={() => setClasses(on ? chosen.filter((x) => x !== c.label) : [...chosen, c.label])}>
                    <i style={{ background: c.color }} aria-hidden />
                    <span>{c.desc ?? c.label}</span>
                    <b>{classCounts[c.label] ?? 0}</b>
                  </button>
                );
              })}
            </div>
            <p className="ad-note">Tap a colour of the map to count it as at risk or not. The number is how many places{where} have it.</p>
          </details>
        )}

        {prov && (
          <div className="ad-filterbar">
            Showing <strong>{prov}</strong> only
            <button onClick={() => setProv("")}>Show all provinces ✕</button>
          </div>
        )}

        {payload && acts && (
          <>
            <div className="ad-kpis">
              <div className="ad-kpi">
                <span className="ad-kpi-icon warn"><Icon name="pin" /></span>
                <span className="ad-kpi-v">{cov.vulnerable}</span>
                <span className="ad-kpi-k">Places at risk</span>
                <span className="ad-kpi-s">of {towns} municipalities</span>
              </div>
              <div className="ad-kpi">
                <span className="ad-kpi-icon good"><Icon name="check" /></span>
                <span className="ad-kpi-v good">{cov.covered}</span>
                <span className="ad-kpi-k">Have an activity</span>
                <span className="ad-kpi-bar"><span style={{ width: `${pct}%` }} /></span>
              </div>
              <button className={`ad-kpi as-button${cov.gaps.length ? " alert" : ""}`} onClick={() => {
                setView("gaps");
                listRef.current?.scrollIntoView({ behavior: "smooth" });
              }}>
                <span className="ad-kpi-icon bad"><Icon name="alert" /></span>
                <span className="ad-kpi-v bad">{cov.gaps.length}</span>
                <span className="ad-kpi-k">Need attention</span>
                <span className="ad-kpi-s">{cov.gaps.length ? "no activity yet – see list ›" : "all covered"}</span>
              </button>
              <div className="ad-kpi">
                <span className="ad-kpi-icon"><Icon name="list" /></span>
                <span className="ad-kpi-v">{total}</span>
                <span className="ad-kpi-k">Activities</span>
                <span className="ad-kpi-s">{cov.counts.ongoing} ongoing · {cov.counts.to_conduct} to conduct</span>
              </div>
              <div className="ad-kpi">
                <span className="ad-kpi-icon"><Icon name="people" /></span>
                <span className="ad-kpi-v">{fmtNumber(cov.farmers, 0)}</span>
                <span className="ad-kpi-k">Farmers reached</span>
                <span className="ad-kpi-s">
                  {cov.fcas ? `and ${fmtNumber(cov.fcas, 0)} farmer group${cov.fcas === 1 ? "" : "s"} (FCA)` : "individual beneficiaries"}
                </span>
              </div>
              <div className="ad-kpi">
                <span className="ad-kpi-icon"><Icon name="peso" /></span>
                <span className="ad-kpi-v">{money(cov.budget)}</span>
                <span className="ad-kpi-k">Budget</span>
                <span className="ad-kpi-s">for these activities</span>
              </div>
            </div>

            <div className="ad-grid">
              <section className="ad-card ad-map-card">
                <header>
                  <h2>Where are the places at risk?</h2>
                  <p>Tap a place to see its activities.</p>
                </header>
                <CoverageMap state={mapState} names={byKey} onPick={pickArea} />
              </section>

              <div className="ad-stack">
                <section className="ad-card">
                  <header>
                    <h2>Where are the activities now?</h2>
                    <p>Status of the {total} activities in the places at risk{where}.</p>
                  </header>
                  <HBars items={ACTIVITY_STATUSES.map((s) => ({ label: s.label, value: cov.counts[s.id], color: s.color }))} />
                </section>
                <section className="ad-card">
                  <header>
                    <h2>What kind of activities?</h2>
                  </header>
                  {categories.length ? (
                    <HBars items={categories.map(([label, value]) => ({ label, value, color: "#0b6237" }))} />
                  ) : (
                    <p className="ad-empty">No activities in the places at risk yet.</p>
                  )}
                </section>
                <section className="ad-card">
                  <header>
                    <h2>By province</h2>
                    <p>Places at risk: <b className="good-t">green</b> have an activity, <b className="bad-t">red</b> do not yet. Tap a province.</p>
                  </header>
                  <ProvinceChart rows={perProvince} onPick={setProv} picked={prov} />
                </section>
              </div>

              <section className="ad-card">
                <header>
                  <h2>How many places in each map colour?</h2>
                  <p>{layers.length > 1 ? "Worst period of each place. " : ""}Faded colours are not counted as at risk.</p>
                </header>
                {legend && (
                  <HBars items={legend.classes.map((c) => ({
                    label: c.desc ?? c.label, value: classCounts[c.label] ?? 0, color: c.color, dim: !chosen.includes(c.label),
                  }))} />
                )}
              </section>

              <section className="ad-card">
                <header>
                  <h2>When do the activities start?</h2>
                  <p>Activities in the places at risk{where}, by the month they start.</p>
                </header>
                <MonthChart acts={atRiskActs} />
                <StatusKey />
              </section>
            </div>

            <section className="ad-card ad-list-card" ref={listRef}>
              <header className="ad-list-head">
                <div>
                  <h2>Places and their activities</h2>
                  <p>Tap a place to open its activities.</p>
                </div>
                <input type="search" placeholder="Search a place or activity…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
              </header>
              <div className="ad-list-tools">
                <div className="ad-seg" role="tablist" aria-label="Show">
                  {([
                    ["risk", `At risk (${cov.vulnerable})`],
                    ["gaps", `Need attention (${cov.gaps.length})`],
                    ["covered", `Have activities (${cov.covered})`],
                    ["all", "All places"],
                  ] as [View, string][]).map(([v, label]) => (
                    <button key={v} role="tab" aria-selected={view === v} className={view === v ? "on" : ""} onClick={() => setView(v)}>
                      {label}
                    </button>
                  ))}
                </div>
                <select value={prov} onChange={(e) => setProv(e.target.value)} aria-label="Province">
                  <option value="">All provinces</option>
                  {provinces.map((p) => <option key={p}>{p}</option>)}
                </select>
              </div>
              {rows.length === 0 ? (
                <p className="ad-empty">{view === "gaps" ? "Every place at risk has an activity. 🎉" : "No place matches."}</p>
              ) : (
                <ul className="ad-areas">
                  {rows.map(({ key, atRisk, gap }) => {
                    const g = byKey.get(key);
                    const c = byArea[key];
                    const list = actsByArea.get(key) ?? [];
                    const counts = emptyCounts();
                    for (const a of list) counts[a.status] += 1;
                    return (
                      <li key={key} id={`area-${key}`} className={atRisk ? (gap ? "bad" : "ok") : ""}>
                        <details open={open === key} onToggle={(e) => {
                          const isOpen = (e.target as HTMLDetailsElement).open;
                          if (isOpen) setOpen(key);
                          else if (open === key) setOpen(null);
                        }}>
                          <summary>
                            <span className={`ad-dot ${atRisk ? (gap ? "bad" : "ok") : "calm"}`} aria-hidden />
                            <span className="ad-area-name">
                              <strong>{g?.name ?? key}</strong>
                              <span>{g?.province}</span>
                            </span>
                            {c ? <ClassDot label={className(c.class)} color={c.color} /> : <span className="ad-muted">No data</span>}
                            <span className="ad-counts">
                              {list.length === 0 ? (
                                <span className={atRisk ? "ad-none" : "ad-muted"}>{atRisk ? "Needs attention" : "No activity"}</span>
                              ) : (
                                ACTIVITY_STATUSES.filter((s) => counts[s.id]).map((s) => (
                                  <span key={s.id} className="ad-count" style={{ color: s.color, background: `${s.color}1a` }}>
                                    {counts[s.id]} {s.label.toLowerCase()}
                                  </span>
                                ))
                              )}
                            </span>
                            <span className="ad-chev" aria-hidden>›</span>
                          </summary>
                          {list.length > 0 ? (
                            <ul className="ad-list">
                              {list.map((a) => (
                                <li key={a.id}>
                                  <StatusChip status={a.status} />
                                  <div>
                                    <strong>{a.title}</strong>
                                    <div className="ad-meta">
                                      {[a.category, dateRange(a), a.office,
                                        a.units != null && `${fmtNumber(a.units, 0)} unit${a.units === 1 ? "" : "s"}`,
                                        beneficiariesText(a.beneficiaries, a.beneficiary_type),
                                        a.budget != null && `₱${fmtNumber(a.budget, 0)}`]
                                        .filter(Boolean).map((x, i) => <span key={i}>{x}</span>)}
                                    </div>
                                    {a.area_keys.length > 1 && (
                                      <div className="ad-also">
                                        Also in {placesSummary(a.area_keys.filter((x) => x !== key), geo.gazetteer, 4)}
                                      </div>
                                    )}
                                    {a.remarks && <div className="ad-remarks">{a.remarks}</div>}
                                  </div>
                                </li>
                              ))}
                            </ul>
                          ) : (
                            <p className="ad-list ad-muted">No activity recorded for this place yet.</p>
                          )}
                        </details>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </>
        )}
        <footer className="ad-foot">
          Department of Agriculture – Regional Field Office, Cordillera Administrative Region · AMIA Program
        </footer>
      </main>
    </div>
  );
}
