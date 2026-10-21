"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ACTIVITY_STATUSES, beneficiariesText, BENEFICIARY_TYPES, coverage, defaultVulnerableClasses, emptyCounts, inAny,
  placesSummary, statusLabel, worstClasses,
  type Activity, type ActivityStatus, type StatusCounts,
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
const PAGE_SIZE = 15;

/** Months / days of an issue (one map each); season and %-of-normal maps are left out of "all". */
const periodLayers = (p: Payload) => p.layers.filter((l) => /^(m|d)_/.test(l.id));

const money = (n: number) =>
  n >= 1e9 ? `₱${fmtNumber(n / 1e9, 1)}B` : n >= 1e6 ? `₱${fmtNumber(n / 1e6, 1)}M` : n >= 1e4 ? `₱${fmtNumber(n / 1e3, 0)}K` : `₱${fmtNumber(n, 0)}`;
const plural = (n: number, one: string, many = `${one}s`) => `${fmtNumber(n, 0)} ${n === 1 ? one : many}`;

// ------------------------------------------------------------------ icons ---

const PATHS = {
  pin: "M12 2a7 7 0 0 0-7 7c0 5.2 7 13 7 13s7-7.8 7-13a7 7 0 0 0-7-7Zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5Z",
  check: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm-1.4 14.2-4.3-4.3 1.4-1.4 2.9 2.9 6.1-6.1 1.4 1.4-7.5 7.5Z",
  alert: "M12 2 1 21h22L12 2Zm1 15h-2v-2h2v2Zm0-4h-2V9h2v4Z",
  list: "M4 5h2v2H4V5Zm4 0h12v2H8V5ZM4 11h2v2H4v-2Zm4 0h12v2H8v-2Zm-4 6h2v2H4v-2Zm4 0h12v2H8v-2Z",
  people: "M16 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm-8 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm0 2c-2.7 0-8 1.3-8 4v3h10v-3c0-1 .4-1.9 1.1-2.6A13 13 0 0 0 8 13Zm8 0c-.3 0-.6 0-1 .1 1.2.9 2 2 2 3.9v3h7v-3c0-2.7-5.3-4-8-4Z",
  peso: "M7 3h6a6 6 0 0 1 5.9 5H21v2h-2.1a6 6 0 0 1 0 1H21v2h-2.1A6 6 0 0 1 13 17H9v4H7v-8H5v-2h2v-1H5V8h2V3Zm2 2v3h7.8A4 4 0 0 0 13 5H9Zm0 5v1h8a4 4 0 0 0 0-1H9Zm0 3v2h4a4 4 0 0 0 3.8-2H9Z",
  search: "M10 2a8 8 0 0 1 6.3 12.9l5.4 5.4-1.4 1.4-5.4-5.4A8 8 0 1 1 10 2Zm0 2a6 6 0 1 0 0 12 6 6 0 0 0 0-12Z",
  download: "M11 3h2v9.2l3.3-3.3 1.4 1.4L12 16l-5.7-5.7 1.4-1.4 3.3 3.3V3ZM4 18h16v2H4v-2Z",
  close: "M6.4 5 12 10.6 17.6 5 19 6.4 13.4 12l5.6 5.6-1.4 1.4-5.6-5.6L6.4 19 5 17.6l5.6-5.6L5 6.4 6.4 5Z",
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

/** Donut of the activities by status; a segment or a key item filters by that status. */
function StatusDonut({ counts, active, onPick }: { counts: StatusCounts; active: ActivityStatus[]; onPick: (s: ActivityStatus) => void }) {
  const total = ACTIVITY_STATUSES.reduce((s, x) => s + counts[x.id], 0);
  const r = 54;
  const c = 2 * Math.PI * r;
  let at = 0;
  return (
    <div className="ad-donut">
      <svg viewBox="0 0 140 140" width={170} height={170} role="img" aria-label="Activities by status">
        <circle cx="70" cy="70" r={r} fill="none" stroke="#eef2ef" strokeWidth="20" />
        {total > 0 && ACTIVITY_STATUSES.map((s) => {
          const n = counts[s.id];
          if (!n) return null;
          const len = (n / total) * c;
          const seg = (
            <circle key={s.id} cx="70" cy="70" r={r} fill="none" stroke={s.color} strokeWidth="20"
              strokeDasharray={`${Math.max(0, len - 2)} ${c}`} strokeDashoffset={-at} transform="rotate(-90 70 70)"
              className={`ad-donut-seg${active.length && !active.includes(s.id) ? " dim" : ""}`}
              onClick={() => onPick(s.id)}>
              <title>{`${s.label}: ${n}`}</title>
            </circle>
          );
          at += len;
          return seg;
        })}
        <text x="70" y="68" textAnchor="middle" className="ad-donut-big">{total}</text>
        <text x="70" y="88" textAnchor="middle" className="ad-donut-small">activities</text>
      </svg>
      <ul className="ad-donut-key">
        {ACTIVITY_STATUSES.map((s) => (
          <li key={s.id}>
            <button className={active.includes(s.id) ? "on" : active.length ? "dim" : ""} aria-pressed={active.includes(s.id)}
              onClick={() => onPick(s.id)}>
              <i style={{ background: s.color }} aria-hidden />
              <span>{s.label}</span>
              <b>{counts[s.id]}</b>
              <small>{total ? `${Math.round((counts[s.id] / total) * 100)}%` : ""}</small>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Horizontal bars with the number at the end; with onPick, a bar filters by its label. */
function HBars({ items, onPick, active }: {
  items: { label: string; value: number; color: string; dim?: boolean }[];
  onPick?: (label: string) => void;
  active?: string;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <ul className={`ad-hbars${onPick ? " pick" : ""}`}>
      {items.map((i) => {
        const inner = (
          <>
            <span className="ad-hbar-label" title={i.label}>{i.label}</span>
            <span className="ad-hbar-track">
              <span className="ad-hbar" style={{ width: `${(i.value / max) * 100}%`, background: i.color }} />
            </span>
            <span className="ad-hbar-val">{fmtNumber(i.value, 0)}</span>
          </>
        );
        const dim = i.dim || (active && active !== i.label);
        return (
          <li key={i.label} className={dim ? "dim" : ""}>
            {onPick ? (
              <button onClick={() => onPick(i.label)} aria-pressed={active === i.label} title={`Show only: ${i.label}`}>{inner}</button>
            ) : inner}
          </li>
        );
      })}
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

function ClassDot({ label, color }: { label: string; color: string }) {
  return (
    <span className="ad-class">
      <i style={{ background: color }} aria-hidden />
      {label}
    </span>
  );
}

/** One activity: status, title, facts, other places, remarks. */
function ActivityItem({ a, here, geo }: { a: Activity; here?: string; geo: Gazetteer }) {
  return (
    <li>
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
            {here ? "Also in " : "In "}{placesSummary(a.area_keys.filter((x) => x !== here), geo.gazetteer, 4)}
          </div>
        )}
        {a.remarks && <div className="ad-remarks">{a.remarks}</div>}
      </div>
    </li>
  );
}

// ------------------------------------------------------------ coverage map ---

/** What the map is coloured by: coverage (at risk with / without an activity) or a total per municipality. */
type Measure = "coverage" | "units" | "beneficiaries" | "budget";
const MEASURES: { id: Measure; label: string }[] = [
  { id: "coverage", label: "Activity coverage" },
  { id: "units", label: "Units delivered" },
  { id: "beneficiaries", label: "Beneficiaries" },
  { id: "budget", label: "Budget" },
];
const SHADES = ["#d7eedb", "#a6d8ae", "#6cbf7a", "#2e9447", "#0b6237"];
const NONE = "#f1f3f2";

export interface Shade {
  label: string; // e.g. "Units delivered"
  values: Map<string, number>;
  breaks: number[]; // upper bound of each class
  fmt: (n: number) => string;
  whole: boolean; // whole numbers: classes read "1–3", "4–7"
}

/** Up to five classes from the quantiles of the values above 0, rounded to readable numbers. */
function makeBreaks(values: number[], whole: boolean): number[] {
  const v = values.filter((x) => x > 0).sort((a, b) => a - b);
  if (!v.length) return [];
  const nice = (x: number) => {
    if (whole && x < 10) return Math.ceil(x);
    const p = 10 ** Math.max(0, Math.floor(Math.log10(x)) - 1);
    return Math.ceil(x / p) * p;
  };
  const out: number[] = [];
  for (let i = 1; i <= 5; i++) {
    const b = nice(v[Math.min(v.length - 1, Math.ceil((i / 5) * v.length) - 1)]);
    if (!out.length || b > out[out.length - 1]) out.push(b);
  }
  return out;
}
const shadeOf = (sh: Shade, v: number) => {
  if (!(v > 0)) return NONE;
  const i = sh.breaks.findIndex((b) => v <= b);
  const k = i < 0 ? sh.breaks.length - 1 : i;
  // spread the classes over the palette when there are fewer than five
  return SHADES[sh.breaks.length === 1 ? SHADES.length - 1 : Math.round((k / (sh.breaks.length - 1)) * (SHADES.length - 1))];
};
const classLabels = (sh: Shade) =>
  sh.breaks.map((b, i) => {
    if (i === 0) return sh.whole && b === 1 ? sh.fmt(1) : `up to ${sh.fmt(b)}`;
    const lo = sh.breaks[i - 1];
    return sh.whole ? (lo + 1 === b ? sh.fmt(b) : `${sh.fmt(lo + 1)}–${sh.fmt(b)}`) : `${sh.fmt(lo)}–${sh.fmt(b)}`;
  });

type Geo = { type: string; features: { properties: Record<string, any>; geometry: { type: string; coordinates: any } }[] };
type MapState = Record<string, "ok" | "bad" | "calm">;

/** CAR municipalities as SVG: green = at risk with an activity, red = at risk without, grey = not at risk. Zooms to a
 * province; the selected place is outlined. */
function CoverageMap({ state, names, onPick, selected, province, counts, shade }: {
  state: MapState;
  names: Map<string, { name: string; province: string }>;
  onPick: (k: string) => void;
  selected: string | null;
  province: string;
  counts: Map<string, number>;
  shade?: Shade | null; // colour by a total per municipality instead of coverage
}) {
  const [geo, setGeo] = useState<{ muni: Geo; prov: Geo } | null>(null);
  const [hover, setHover] = useState<{ key: string; x: number; y: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);
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
    const px = (x: number) => (x - x0) * k * s;
    const py = (y: number) => (y1 - y) * s;
    const path = (g: Geo["features"][0]["geometry"]) =>
      rings(g).map((ring) => "M" + ring.map(([x, y]) => `${px(x).toFixed(1)},${py(y).toFixed(1)}`).join("L") + "Z").join("");
    const bounds = (g: Geo["features"][0]["geometry"]) => {
      let a = Infinity, b = Infinity, c = -Infinity, d = -Infinity;
      for (const ring of rings(g)) for (const [x, y] of ring) {
        a = Math.min(a, px(x)); c = Math.max(c, px(x)); b = Math.min(b, py(y)); d = Math.max(d, py(y));
      }
      return [a, b, c, d];
    };
    return {
      W, H,
      muni: geo.muni.features.map((f) => ({ key: f.properties.area_key as string, d: path(f.geometry), b: bounds(f.geometry) })),
      prov: geo.prov.features.map((f, i) => ({ key: String(i), d: path(f.geometry) })),
    };
  }, [geo]);
  if (!view) return <div className="ad-map-loading">Loading map…</div>;
  // zoom to the province (with a margin), else the whole region
  let vb = `-6 -6 ${view.W + 12} ${view.H + 12}`;
  if (province) {
    const bs = view.muni.filter((m) => names.get(m.key)?.province === province).map((m) => m.b);
    if (bs.length) {
      const a = Math.min(...bs.map((b) => b[0])), b = Math.min(...bs.map((x) => x[1]));
      const c = Math.max(...bs.map((x) => x[2])), d = Math.max(...bs.map((x) => x[3]));
      const pad = Math.max(c - a, d - b) * 0.08;
      vb = `${a - pad} ${b - pad} ${c - a + 2 * pad} ${d - b + 2 * pad}`;
    }
  }
  const h = hover ? names.get(hover.key) : null;
  const fill = (k: string) =>
    shade ? shadeOf(shade, shade.values.get(k) ?? 0) : state[k] === "ok" ? GOOD : state[k] === "bad" ? BAD : CALM;
  const order = [...view.muni].sort((a, b) => Number(a.key === selected) - Number(b.key === selected));
  return (
    <div className="ad-map" ref={box} onMouseLeave={() => setHover(null)}>
      <svg viewBox={vb} role="img" aria-label="Map of the municipalities: green with an activity, red needs attention">
        {order.map((m) => {
          const other = province && names.get(m.key)?.province !== province;
          return (
            <path key={m.key} d={m.d} fill={fill(m.key)}
              className={`ad-map-area${hover?.key === m.key ? " hover" : ""}${selected === m.key ? " sel" : ""}${other ? " other" : ""}${shade && state[m.key] === "bad" ? " gap" : ""}`}
              onMouseMove={(e) => {
                const r = box.current?.getBoundingClientRect();
                if (r) setHover({ key: m.key, x: e.clientX - r.left, y: e.clientY - r.top });
              }}
              onClick={() => onPick(m.key)} tabIndex={0} role="button" aria-label={names.get(m.key)?.name}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onPick(m.key))} />
          );
        })}
        {view.prov.map((p) => <path key={p.key} d={p.d} className="ad-map-prov" />)}
      </svg>
      {h && hover && (
        <div className="ad-map-tip on" style={{ left: Math.min(hover.x + 14, (box.current?.clientWidth ?? 400) - 210), top: hover.y + 14 }} aria-hidden>
          <strong>{h.name}</strong> <span>{h.province}</span>
          <em className={state[hover.key] ?? "calm"}>
            {state[hover.key] === "ok" ? "At risk · has an activity" : state[hover.key] === "bad" ? "At risk · needs attention" : "Not at risk"}
          </em>
          {shade && <b className="ad-map-tip-v">{shade.label}: {shade.fmt(shade.values.get(hover.key) ?? 0)}</b>}
          <span>{plural(counts.get(hover.key) ?? 0, "activity", "activities")} · click for details</span>
        </div>
      )}
      {shade ? (
        <ul className="ad-key">
          <li className="ad-key-title">{shade.label}:</li>
          <li><i style={{ background: NONE, border: "1px solid #d5dbd7" }} /> None</li>
          {classLabels(shade).map((l, i) => (
            <li key={l}><i style={{ background: shadeOf(shade, shade.breaks[i]) }} /> {l}</li>
          ))}
          <li><i className="ad-key-gap" /> At risk, no activity yet</li>
        </ul>
      ) : (
        <ul className="ad-key">
          <li><i style={{ background: GOOD }} /> At risk, has an activity</li>
          <li><i style={{ background: BAD }} /> At risk, no activity yet</li>
          <li><i style={{ background: CALM }} /> Not at risk</li>
        </ul>
      )}
    </div>
  );
}

// ------------------------------------------------------------ table & CSV ---

type SortKey = "title" | "places" | "status" | "units" | "beneficiaries" | "budget" | "office" | "start_date";
const STATUS_ORDER = Object.fromEntries(ACTIVITY_STATUSES.map((s, i) => [s.id, i]));

function csvOf(rows: Activity[], geo: Gazetteer): string {
  const name = new Map(geo.gazetteer.map((g) => [g.area_key, `${g.name} (${g.province})`]));
  const head = ["Activity", "Places", "Status", "Category", "No. of units", "Beneficiary type", "Beneficiaries", "Budget (PHP)",
    "Office", "Start date", "End date", "Remarks"];
  const q = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = rows.map((a) => [a.title, a.area_keys.map((k) => name.get(k) ?? k).join("; "), statusLabel(a.status), a.category,
    a.units, BENEFICIARY_TYPES.find((b) => b.id === a.beneficiary_type)?.label, a.beneficiaries, a.budget, a.office,
    a.start_date, a.end_date, a.remarks].map(q).join(","));
  return "﻿" + [head.join(","), ...lines].join("\n");
}

function ActivitiesTable({ rows, geo }: { rows: Activity[]; geo: Gazetteer }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "status", dir: 1 });
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [rows, sort]);
  const sorted = useMemo(() => {
    const val = (a: Activity): string | number => {
      switch (sort.key) {
        case "places": return placesSummary(a.area_keys, geo.gazetteer, 1);
        case "status": return STATUS_ORDER[a.status];
        case "units": return a.units ?? -1;
        case "beneficiaries": return a.beneficiaries ?? -1;
        case "budget": return a.budget ?? -1;
        case "office": return a.office ?? "";
        case "start_date": return a.start_date ?? "9999";
        default: return a.title;
      }
    };
    return [...rows].sort((a, b) => {
      const x = val(a), y = val(b);
      return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * sort.dir
        || a.title.localeCompare(b.title);
    });
  }, [rows, sort, geo]);
  const pages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const shown = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const th = (key: SortKey, label: string, num = false) => (
    <th className={num ? "num" : ""} aria-sort={sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button onClick={() => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : 1 }))}>
        {label}<span className="ad-sort" aria-hidden>{sort.key === key ? (sort.dir === 1 ? "▲" : "▼") : "↕"}</span>
      </button>
    </th>
  );
  if (!rows.length) return <p className="ad-empty">No activity matches the filters.</p>;
  return (
    <>
      <div className="ad-table-wrap">
        <table className="ad-table">
          <thead>
            <tr>
              {th("title", "Activity")}
              {th("places", "Places")}
              {th("status", "Status")}
              {th("units", "Units", true)}
              {th("beneficiaries", "Beneficiaries", true)}
              {th("budget", "Budget", true)}
              {th("office", "Office")}
              {th("start_date", "Dates")}
            </tr>
          </thead>
          <tbody>
            {shown.map((a) => (
              <tr key={a.id}>
                <td><strong>{a.title}</strong>{a.category && <small>{a.category}</small>}</td>
                <td>{placesSummary(a.area_keys, geo.gazetteer, 2)}{a.area_keys.length > 1 && <small>{a.area_keys.length} municipalities</small>}</td>
                <td><StatusChip status={a.status} /></td>
                <td className="num">{a.units != null ? fmtNumber(a.units, 0) : "–"}</td>
                <td className="num">{beneficiariesText(a.beneficiaries, a.beneficiary_type) || "–"}</td>
                <td className="num">{a.budget != null ? `₱${fmtNumber(a.budget, 0)}` : "–"}</td>
                <td>{a.office ?? "–"}</td>
                <td className="nowrap">{dateRange(a) || "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="ad-pager">
        <span>{sorted.length > PAGE_SIZE ? `${page * PAGE_SIZE + 1}–${Math.min(sorted.length, (page + 1) * PAGE_SIZE)} of ` : ""}{plural(sorted.length, "activity", "activities")}</span>
        {pages > 1 && (
          <span className="ad-pager-btns">
            <button disabled={page === 0} onClick={() => setPage(page - 1)} aria-label="Previous page">‹</button>
            <span>Page {page + 1} of {pages}</span>
            <button disabled={page >= pages - 1} onClick={() => setPage(page + 1)} aria-label="Next page">›</button>
          </span>
        )}
      </div>
    </>
  );
}

// ------------------------------------------------------------------ page ---

type View = "risk" | "gaps" | "covered" | "all";
type Tab = "places" | "activities";

export default function ActivitiesDashboard({ geo }: { geo: Gazetteer }) {
  const [catalog, setCatalog] = useState<CatalogEntry[] | null>(null);
  const [acts, setActs] = useState<Activity[] | null>(null);
  const type: ProductType = "envi"; // the El Niño Action Plan follows the El Niño Vulnerability Index only
  const [productId, setProductId] = useState<string | null>(null);
  const [payload, setPayload] = useState<Payload | null>(null);
  const [layerId, setLayerId] = useState<string | null>(null);
  const [classes, setClasses] = useState<string[] | null>(null);
  // filters: they apply to the whole page
  const [prov, setProv] = useState("");
  const [statuses, setStatuses] = useState<ActivityStatus[]>([]);
  const [category, setCategory] = useState("");
  const [office, setOffice] = useState("");
  const [q, setQ] = useState("");
  const [view, setView] = useState<View>("risk");
  const [tab, setTab] = useState<Tab>("places");
  const [selected, setSelected] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [measure, setMeasure] = useState<Measure>("coverage");
  const [item, setItem] = useState(""); // units: one item (activity title), or all
  const [openProvs, setOpenProvs] = useState<string[]>([]); // provinces opened in the place list
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
  const inProv = (k: string) => !prov || byKey.get(k)?.province === prov;

  // the activities after the status / type / office filters (the province filter works on places)
  const allActs = useMemo(() => acts ?? [], [acts]);
  const relevant = useMemo(
    () => allActs.filter((a) => (!statuses.length || statuses.includes(a.status)) && (!category || (a.category || "Other") === category)
      && (!office || (a.office || "Not given") === office)),
    [allActs, statuses, category, office],
  );
  const categoriesAll = useMemo(() => [...new Set(allActs.map((a) => a.category || "Other"))].sort(), [allActs]);
  const officesAll = useMemo(() => [...new Set(allActs.map((a) => a.office || "Not given"))].sort(), [allActs]);

  const classCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const [k, v] of Object.entries(byArea)) if (inProv(k)) c[v.class] = (c[v.class] ?? 0) + 1;
    return c;
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
        .filter(inProv)
        .sort((a, b) => byArea[b].rank - byArea[a].rank || (byKey.get(a)?.name ?? "").localeCompare(byKey.get(b)?.name ?? "")),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [allRisk, prov, byKey, byArea],
  );
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
  // totals per municipality for the map (an activity in several places is shared evenly between them)
  const items = useMemo(() => [...new Set(relevant.filter((a) => a.units != null).map((a) => a.title))].sort(), [relevant]);
  const shade: Shade | null = useMemo(() => {
    if (measure === "coverage") return null;
    const get = (a: Activity) => (measure === "units" ? a.units : measure === "beneficiaries" ? a.beneficiaries : a.budget);
    const values = new Map<string, number>();
    for (const a of relevant) {
      const v = get(a);
      if (v == null || (measure === "units" && item && a.title !== item)) continue;
      for (const k of a.area_keys) values.set(k, (values.get(k) ?? 0) + v / a.area_keys.length);
    }
    const whole = measure !== "budget";
    const fmt = measure === "budget" ? (n: number) => money(n) : (n: number) => fmtNumber(Math.round(n * 10) / 10, n % 1 ? 1 : 0);
    const label = measure === "units" ? (item ? `${item} (units)` : "Units delivered") : measure === "beneficiaries" ? "Beneficiaries" : "Budget";
    return { label, values, breaks: makeBreaks([...values.values()], whole), fmt, whole };
  }, [measure, item, relevant]);
  const countByArea = useMemo(() => new Map([...actsByArea.entries()].map(([k, v]) => [k, v.length])), [actsByArea]);
  const mapState = useMemo(() => {
    const out: MapState = {};
    const gaps = new Set(coverage(allRisk, relevant).gaps);
    for (const k of allRisk) out[k] = gaps.has(k) ? "bad" : "ok";
    return out;
  }, [allRisk, relevant]);
  const perProvince = useMemo(
    () => provinces.map((p) => ({ province: p, ...coverage(allRisk.filter((k) => byKey.get(k)?.province === p), relevant) })),
    [provinces, allRisk, relevant, byKey],
  );
  const bars = (key: (a: Activity) => string) => {
    const c = new Map<string, number>();
    for (const a of atRiskActs) c.set(key(a), (c.get(key(a)) ?? 0) + 1);
    return [...c.entries()].sort((a, b) => b[1] - a[1]).slice(0, 7);
  };
  const categories = useMemo(() => bars((a) => a.category || "Other"), [atRiskActs]); // eslint-disable-line react-hooks/exhaustive-deps
  const offices = useMemo(() => bars((a) => a.office || "Not given"), [atRiskActs]); // eslint-disable-line react-hooks/exhaustive-deps
  const hasDates = atRiskActs.some((a) => a.start_date);

  const s = q.trim().toLowerCase();
  const rows = useMemo(() => {
    const gaps = new Set(cov.gaps);
    const keys =
      view === "all"
        ? geo.gazetteer.map((g) => g.area_key).filter(inProv).sort(
            (a, b) => (byArea[b]?.rank ?? -1) - (byArea[a]?.rank ?? -1) || (byKey.get(a)?.name ?? "").localeCompare(byKey.get(b)?.name ?? ""),
          )
        : vulnerable.filter((k) => (view === "gaps" ? gaps.has(k) : view === "covered" ? !gaps.has(k) : true));
    const risk = new Set(vulnerable);
    return keys
      .filter((k) => !s || byKey.get(k)?.name.toLowerCase().includes(s) || (actsByArea.get(k) ?? []).some((a) => a.title.toLowerCase().includes(s)))
      .map((k) => ({ key: k, atRisk: risk.has(k), gap: gaps.has(k) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, vulnerable, cov.gaps, geo, byArea, byKey, prov, s, actsByArea]);
  // the activities table: every activity after the filters, in the province, matching the search
  const tableRows = useMemo(
    () => relevant.filter((a) => (!prov || a.area_keys.some(inProv))
      && (!s || a.title.toLowerCase().includes(s) || (a.office ?? "").toLowerCase().includes(s)
        || a.area_keys.some((k) => byKey.get(k)?.name.toLowerCase().includes(s)))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [relevant, prov, s, byKey],
  );

  const toggleStatus = (st: ActivityStatus) => setStatuses((xs) => (xs.includes(st) ? xs.filter((x) => x !== st) : [...xs, st]));
  const filtered = !!(prov || statuses.length || category || office || s);
  const reset = () => {
    setProv(""); setStatuses([]); setCategory(""); setOffice(""); setQ(""); setSelected(null);
  };
  const toList = (v?: View) => {
    if (v) setView(v);
    setTab("places");
    listRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const openInList = (k: string) => {
    if (prov && byKey.get(k)?.province !== prov) setProv("");
    setView(mapState[k] ? "risk" : "all");
    setTab("places");
    setQ("");
    setOpen(k);
    const p = byKey.get(k)?.province;
    if (p) setOpenProvs((xs) => (xs.includes(p) ? xs : [...xs, p]));
    setTimeout(() => document.getElementById(`area-${k}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 60);
  };

  const loading = !error && (catalog === null || acts === null || (entry && !payload));
  const total = ACTIVITY_STATUSES.reduce((sum, x) => sum + cov.counts[x.id], 0);
  const where = prov ? ` in ${prov}` : "";
  const mapsHref = `/?type=envi${entry ? `&p=${encodeURIComponent(entry.id)}` : ""}`;
  const towns = prov ? geo.gazetteer.filter((g) => g.province === prov).length : geo.gazetteer.length;
  const pct = cov.vulnerable ? Math.round((cov.covered / cov.vulnerable) * 100) : 0;
  const sel = selected ? byKey.get(selected) : null;
  const selActs = selected ? actsByArea.get(selected) ?? [] : [];
  const selClass = selected ? byArea[selected] : null;

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
              <li><strong>Click a place</strong> on the map to see its activities beside the map. Use the <strong>filter bar</strong> –
                province, status, type of activity, office or search – to narrow everything on the page. Bars and the status
                chart can be clicked too.</li>
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
                    {payload.layers.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
                    {periodLayers(payload).length > 1 && <option value={ALL}>Worst month of the outlook</option>}
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

        {payload && acts && (
          <>
            {/* one filter bar for the whole page */}
            <div className="ad-filters" role="search">
              <label className="ad-search">
                <Icon name="search" size={18} />
                <input type="search" placeholder="Search a place, activity or office…" value={q} onChange={(e) => setQ(e.target.value)}
                  aria-label="Search" />
              </label>
              <select value={prov} onChange={(e) => { setProv(e.target.value); setSelected(null); }} aria-label="Province" className={prov ? "on" : ""}>
                <option value="">All provinces</option>
                {provinces.map((p) => <option key={p}>{p}</option>)}
              </select>
              <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Type of activity" className={category ? "on" : ""}>
                <option value="">All types</option>
                {categoriesAll.map((c) => <option key={c}>{c}</option>)}
              </select>
              <select value={office} onChange={(e) => setOffice(e.target.value)} aria-label="Office" className={office ? "on" : ""}>
                <option value="">All offices</option>
                {officesAll.map((c) => <option key={c}>{c}</option>)}
              </select>
              <div className="ad-chips" role="group" aria-label="Status">
                {ACTIVITY_STATUSES.map((st) => (
                  <button key={st.id} className={statuses.includes(st.id) ? "on" : ""} aria-pressed={statuses.includes(st.id)}
                    onClick={() => toggleStatus(st.id)} style={{ ["--c" as string]: st.color }}>
                    <i aria-hidden /> {st.label}
                  </button>
                ))}
              </div>
              {filtered && <button className="ad-reset" onClick={reset}>Reset filters</button>}
            </div>

            <div className="ad-kpis">
              <button className="ad-kpi as-button" onClick={() => toList("risk")}>
                <span className="ad-kpi-icon warn"><Icon name="pin" /></span>
                <span className="ad-kpi-v">{cov.vulnerable}</span>
                <span className="ad-kpi-k">Places at risk</span>
                <span className="ad-kpi-s">of {towns} municipalities{where}</span>
              </button>
              <button className="ad-kpi as-button" onClick={() => toList("covered")}>
                <span className="ad-kpi-icon good"><Icon name="check" /></span>
                <span className="ad-kpi-v good">{cov.covered}</span>
                <span className="ad-kpi-k">Have an activity</span>
                <span className="ad-kpi-bar" title={`${pct}%`}><span style={{ width: `${pct}%` }} /></span>
              </button>
              <button className={`ad-kpi as-button${cov.gaps.length ? " alert" : ""}`} onClick={() => toList("gaps")}>
                <span className="ad-kpi-icon bad"><Icon name="alert" /></span>
                <span className="ad-kpi-v bad">{cov.gaps.length}</span>
                <span className="ad-kpi-k">Need attention</span>
                <span className="ad-kpi-s">{cov.gaps.length ? "no activity yet – see list ›" : "all covered"}</span>
              </button>
              <button className="ad-kpi as-button" onClick={() => { setTab("activities"); listRef.current?.scrollIntoView({ behavior: "smooth" }); }}>
                <span className="ad-kpi-icon"><Icon name="list" /></span>
                <span className="ad-kpi-v">{total}</span>
                <span className="ad-kpi-k">Activities</span>
                <span className="ad-kpi-s">{cov.counts.ongoing} ongoing · {cov.counts.to_conduct} to conduct</span>
              </button>
              <div className="ad-kpi">
                <span className="ad-kpi-icon"><Icon name="people" /></span>
                <span className="ad-kpi-v">{fmtNumber(cov.farmers, 0)}</span>
                <span className="ad-kpi-k">Farmers reached</span>
                <span className="ad-kpi-s">
                  {cov.fcas ? `and ${fmtNumber(cov.fcas, 0)} farmer group${cov.fcas === 1 ? "" : "s"} (FCA)` : "individual beneficiaries"}
                </span>
              </div>
              <div className="ad-kpi" title={`₱${fmtNumber(cov.budget, 2)}`}>
                <span className="ad-kpi-icon"><Icon name="peso" /></span>
                <span className="ad-kpi-v">{money(cov.budget)}</span>
                <span className="ad-kpi-k">Budget</span>
                <span className="ad-kpi-s">for these activities</span>
              </div>
            </div>

            {/* the map with the details of the place clicked */}
            <section className="ad-card ad-map-card">
              <header>
                <h2>Where are the places at risk{where}?</h2>
                <p>Hover a place for a quick look; click it to see its activities. Colour it by coverage or by what was delivered.</p>
              </header>
              <div className="ad-map-tools">
                <span className="ad-map-tools-label">Colour the map by</span>
                <div className="ad-seg" role="radiogroup" aria-label="Colour the map by">
                  {MEASURES.map((m) => (
                    <button key={m.id} role="radio" aria-checked={measure === m.id} className={measure === m.id ? "on" : ""}
                      onClick={() => setMeasure(m.id)}>
                      {m.label}
                    </button>
                  ))}
                </div>
                {measure === "units" && (
                  <select value={item} onChange={(e) => setItem(e.target.value)} aria-label="Item" className={item ? "on" : ""}>
                    <option value="">All items (added together)</option>
                    {items.map((t) => <option key={t}>{t}</option>)}
                  </select>
                )}
              </div>
              {measure === "units" && !item && items.length > 1 && (
                <p className="ad-note">Different items are added together – choose one item to compare places fairly.</p>
              )}
              <div className="ad-map-split">
                <CoverageMap state={mapState} names={byKey} onPick={setSelected} selected={selected} province={prov} counts={countByArea}
                  shade={shade} />
                <aside className="ad-panel" aria-live="polite">
                  {sel ? (
                    <>
                      <div className="ad-panel-head">
                        <div>
                          <h3>{sel.name}</h3>
                          <p>{sel.province}</p>
                        </div>
                        <button className="ad-icon-btn" onClick={() => setSelected(null)} aria-label="Close"><Icon name="close" size={18} /></button>
                      </div>
                      <div className="ad-panel-tags">
                        {selClass && <ClassDot label={`ENVI: ${className(selClass.class)}`} color={selClass.color} />}
                        {shade && <span className="ad-tag calm">{shade.label}: {shade.fmt(shade.values.get(selected!) ?? 0)}</span>}
                        <span className={`ad-tag ${mapState[selected!] ?? "calm"}`}>
                          {mapState[selected!] === "ok" ? "Has an activity" : mapState[selected!] === "bad" ? "Needs attention" : "Not at risk"}
                        </span>
                      </div>
                      {selActs.length ? (
                        <ul className="ad-list">{selActs.map((a) => <ActivityItem key={a.id} a={a} here={selected!} geo={geo} />)}</ul>
                      ) : (
                        <p className="ad-empty">No activity recorded for this place{filtered ? " (with the filters)" : ""} yet.</p>
                      )}
                      <button className="ad-link" onClick={() => openInList(selected!)}>Show in the list ›</button>
                    </>
                  ) : (
                    <>
                      <h3>Need attention first</h3>
                      <p className="ad-sub">Places at risk{where} without an activity yet. Click one – or a place on the map.</p>
                      {cov.gaps.length ? (
                        <ul className="ad-gaplist">
                          {cov.gaps.slice(0, 8).map((k) => (
                            <li key={k}>
                              <button onClick={() => setSelected(k)}>
                                <span className="ad-dot bad" aria-hidden />
                                <strong>{byKey.get(k)?.name}</strong>
                                <span>{byKey.get(k)?.province}</span>
                                {byArea[k] && <ClassDot label={className(byArea[k].class)} color={byArea[k].color} />}
                              </button>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="ad-empty">Every place at risk{where} has an activity. 🎉</p>
                      )}
                      {cov.gaps.length > 8 && <button className="ad-link" onClick={() => toList("gaps")}>All {cov.gaps.length} places that need attention ›</button>}
                    </>
                  )}
                </aside>
              </div>
            </section>

            <div className="ad-grid3">
              <section className="ad-card">
                <header>
                  <h2>Status of the activities</h2>
                  <p>In the places at risk{where}. Click a status to filter.</p>
                </header>
                <StatusDonut counts={cov.counts} active={statuses} onPick={toggleStatus} />
              </section>
              <section className="ad-card">
                <header>
                  <h2>By province</h2>
                  <p>Places at risk: <b className="good-t">green</b> have an activity, <b className="bad-t">red</b> do not yet. Click a province.</p>
                </header>
                <ProvinceChart rows={perProvince} onPick={(p) => { setProv(p); setSelected(null); }} picked={prov} />
              </section>
              <section className="ad-card">
                <header>
                  <h2>Places in each map colour</h2>
                  <p>{layers.length > 1 ? "Worst period of each place. " : ""}Faded colours are not counted as at risk.</p>
                </header>
                {legend && (
                  <HBars items={legend.classes.map((c) => ({
                    label: c.desc ?? c.label, value: classCounts[c.label] ?? 0, color: c.color, dim: !chosen.includes(c.label),
                  }))} />
                )}
              </section>
              <section className={`ad-card${hasDates ? "" : " half"}`}>
                <header>
                  <h2>Type of activities</h2>
                  <p>Click a type to filter.</p>
                </header>
                {categories.length ? (
                  <HBars items={categories.map(([label, value]) => ({ label, value, color: "#0b6237" }))}
                    onPick={(c) => setCategory(category === c ? "" : c)} active={category} />
                ) : <p className="ad-empty">No activities in the places at risk yet.</p>}
              </section>
              <section className={`ad-card${hasDates ? "" : " half"}`}>
                <header>
                  <h2>Implementing offices</h2>
                  <p>Click an office to filter.</p>
                </header>
                {offices.length ? (
                  <HBars items={offices.map(([label, value]) => ({ label, value, color: "#1565c0" }))}
                    onPick={(o) => setOffice(office === o ? "" : o)} active={office} />
                ) : <p className="ad-empty">No activities in the places at risk yet.</p>}
              </section>
              {hasDates && (
                <section className="ad-card">
                  <header>
                    <h2>When do the activities start?</h2>
                    <p>By the month they start.</p>
                  </header>
                  <MonthChart acts={atRiskActs} />
                </section>
              )}
            </div>

            <section className="ad-card ad-list-card" ref={listRef}>
              <header className="ad-list-head">
                <div className="ad-tabs" role="tablist" aria-label="List">
                  <button role="tab" aria-selected={tab === "places"} className={tab === "places" ? "on" : ""} onClick={() => setTab("places")}>
                    By place
                  </button>
                  <button role="tab" aria-selected={tab === "activities"} className={tab === "activities" ? "on" : ""} onClick={() => setTab("activities")}>
                    All activities <span className="ad-badge">{tableRows.length}</span>
                  </button>
                </div>
                {tab === "activities" && tableRows.length > 0 && (
                  <button className="ad-dl" onClick={() => {
                    const url = URL.createObjectURL(new Blob([csvOf(tableRows, geo)], { type: "text/csv;charset=utf-8" }));
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = `el-nino-action-plan-activities${prov ? `-${prov.toLowerCase().replace(/\s+/g, "-")}` : ""}.csv`;
                    a.click();
                    URL.revokeObjectURL(url);
                  }}>
                    <Icon name="download" size={18} /> Download CSV
                  </button>
                )}
              </header>

              {tab === "places" ? (
                <>
                  <div className="ad-list-tools">
                    <div className="ad-seg" role="radiogroup" aria-label="Show">
                      {([
                        ["risk", `At risk (${cov.vulnerable})`],
                        ["gaps", `Need attention (${cov.gaps.length})`],
                        ["covered", `Have activities (${cov.covered})`],
                        ["all", "All places"],
                      ] as [View, string][]).map(([v, label]) => (
                        <button key={v} role="radio" aria-checked={view === v} className={view === v ? "on" : ""} onClick={() => setView(v)}>
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                  {rows.length === 0 ? (
                    <p className="ad-empty">{view === "gaps" && !s ? "Every place at risk has an activity. 🎉" : "No place matches."}</p>
                  ) : (
                    <ul className="ad-provlist">
                      {provinces.map((p) => {
                        const group = rows.filter((r) => byKey.get(r.key)?.province === p);
                        if (!group.length) return null;
                        // opened by a click – or always while searching or showing one province
                        const expanded = !!s || prov === p || openProvs.includes(p);
                        const risk = group.filter((r) => r.atRisk).length;
                        const gaps = group.filter((r) => r.gap).length;
                        const actCount = new Set(group.flatMap((r) => (actsByArea.get(r.key) ?? []).map((a) => a.id))).size;
                        const share = risk ? Math.round(((risk - gaps) / risk) * 100) : 0;
                        return (
                          <li key={p} className={`ad-provgroup${expanded ? " open" : ""}`}>
                            <button className="ad-provgroup-head" aria-expanded={expanded}
                              onClick={() => setOpenProvs((xs) => (xs.includes(p) ? xs.filter((x) => x !== p) : [...xs, p]))}>
                              <span className="ad-chev" aria-hidden>›</span>
                              <span className="ad-provgroup-name">
                                <strong>{p}</strong>
                                <span>{plural(group.length, "municipality", "municipalities")}</span>
                              </span>
                              <span className="ad-provgroup-stats">
                                {risk > 0 && <span className="ad-count" style={{ color: "#b45309", background: "#fff1e3" }}>{risk} at risk</span>}
                                {gaps > 0 ? (
                                  <span className="ad-none">{gaps} need{gaps === 1 ? "s" : ""} attention</span>
                                ) : risk > 0 ? (
                                  <span className="ad-count" style={{ color: GOOD, background: `${GOOD}1a` }}>all covered</span>
                                ) : null}
                                <span className="ad-muted">{plural(actCount, "activity", "activities")}</span>
                              </span>
                              {risk > 0 ? (
                                <span className="ad-provgroup-bar" title={`${share}% of the places at risk have an activity`}>
                                  <span style={{ width: `${share}%` }} />
                                  <em>{share}%</em>
                                </span>
                              ) : <span className="ad-provgroup-bar empty" />}
                            </button>
                            {expanded && (
                          <ul className="ad-areas">
                            {group.map(({ key, atRisk, gap }) => {
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
                                    ACTIVITY_STATUSES.filter((st) => counts[st.id]).map((st) => (
                                      <span key={st.id} className="ad-count" style={{ color: st.color, background: `${st.color}1a` }}>
                                        {counts[st.id]} {st.label.toLowerCase()}
                                      </span>
                                    ))
                                  )}
                                </span>
                                <span className="ad-chev" aria-hidden>›</span>
                              </summary>
                              {list.length > 0 ? (
                                <ul className="ad-list">{list.map((a) => <ActivityItem key={a.id} a={a} here={key} geo={geo} />)}</ul>
                              ) : (
                                <p className="ad-list ad-muted">No activity recorded for this place yet.</p>
                              )}
                            </details>
                          </li>
                        );
                      })}
                          </ul>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </>
              ) : (
                <ActivitiesTable rows={tableRows} geo={geo} />
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
