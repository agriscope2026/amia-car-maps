"use client";

import type { ProductType } from "@/lib/types";
import { fmtNumber } from "@/lib/format";
import { enviSentence, SUMMARY_LAYER, type EnviPart, type TrendPoint } from "@/lib/insights";

/** "Why is it High?": what each indicator adds to the ENVI, as one stacked bar on the 0–1 scale with the class
 * breaks marked, and the plain-language sentence. */
export function EnviBar({ name, cls, envi, parts, breaks }: { name: string; cls: string; envi: number; parts: EnviPart[]; breaks?: number[] }) {
  const inner = (breaks ?? [0, 0.2, 0.4, 0.6, 0.8, 1]).slice(1, -1);
  return (
    <div className="envi-why">
      <p className="envi-why-text">{enviSentence(name, cls, envi, parts)}</p>
      <div className="envi-bar" role="img" aria-label={parts.map((p) => `${p.label} ${p.value.toFixed(2)}`).join(", ") + `; ENVI ${envi.toFixed(2)}`}>
        {parts.map((p) => (
          <span key={p.key} style={{ width: `${p.value * 100}%`, background: p.color }} title={`${p.label}: +${p.value.toFixed(2)}`} />
        ))}
        {inner.map((b) => (
          <i key={b} className="envi-tick" style={{ left: `${b * 100}%` }} />
        ))}
      </div>
      <div className="envi-scale" aria-hidden>
        <span>0 · least vulnerable</span>
        <span>1 · most vulnerable</span>
      </div>
      <ul className="envi-parts">
        {parts.map((p) => (
          <li key={p.key}>
            <span className="sw" style={{ background: p.color }} />
            <span className="envi-part-label">{p.label}</span>
            <span className="envi-part-calc">
              {p.norm.toFixed(2)} × {p.weight.toFixed(2)} = <strong>+{p.value.toFixed(2)}</strong>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Small line of an area's value over past issues; dots in the class colour, the latest one bigger. */
export function Sparkline({ points, unit, width = 220, height = 54 }: { points: TrendPoint[]; unit: string; width?: number; height?: number }) {
  const pts = points.filter((p) => p.value !== null);
  if (!pts.length) return null;
  const vals = pts.map((p) => p.value!);
  const lo = 0;
  const hi = unit ? Math.max(...vals, 1) : 1; // ENVI on its fixed 0–1 scale, rainfall from 0 mm
  const pad = 7;
  const x = (i: number) => (pts.length === 1 ? width / 2 : pad + (i * (width - 2 * pad)) / (pts.length - 1));
  const y = (v: number) => height - pad - ((v - lo) / (hi - lo)) * (height - 2 * pad);
  const fmt = (v: number) => (unit ? `${fmtNumber(v, 0)} ${unit}` : v.toFixed(2));
  return (
    <svg className="spark" viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img"
      aria-label={pts.map((p) => `${p.period}: ${fmt(p.value!)}`).join("; ")}>
      <polyline points={pts.map((p, i) => `${x(i)},${y(p.value!)}`).join(" ")} fill="none" stroke="#5f6b66" strokeWidth={1.4} />
      {pts.map((p, i) => (
        <circle key={p.id} cx={x(i)} cy={y(p.value!)} r={i === pts.length - 1 ? 4.2 : 3} fill={p.color} stroke="#222" strokeWidth={0.6}>
          <title>{`${p.period}: ${fmt(p.value!)} (${p.class})`}</title>
        </circle>
      ))}
    </svg>
  );
}

/** "April 2026 – September 2026" → "Apr 2026 – Sep 2026" (short axis labels). */
const shortPeriod = (label: string) => label.replace(/(January|February|March|April|May|June|July|August|September|October|November|December)/g, (m) => m.slice(0, 3));

/** Trend rows for an area (ENVI, 10-day and season rainfall), from /api/public/history. */
export function Trends({ series }: { series: Partial<Record<ProductType, TrendPoint[]>> | null }) {
  if (!series) return <p className="dlg-muted">Loading past issues…</p>;
  const rows = (Object.keys(SUMMARY_LAYER) as ProductType[]).filter((t) => series[t]?.some((p) => p.value !== null));
  if (!rows.length) return <p className="dlg-muted">No published values for this area yet.</p>;
  return (
    <div className="trends">
      {rows.map((t) => {
        const s = SUMMARY_LAYER[t]!;
        const pts = series[t]!.filter((p) => p.value !== null);
        const last = pts[pts.length - 1];
        const prev = pts[pts.length - 2];
        const fmt = (v: number) => (s.unit ? `${fmtNumber(v, 0)} ${s.unit}` : v.toFixed(2));
        const d = prev ? last.value! - prev.value! : null;
        return (
          <div key={t} className="trend">
            <div className="trend-head">
              <strong>{s.label}</strong>
              <span>
                {fmt(last.value!)}
                {d !== null && Math.abs(d) > 1e-9 && (
                  <span className={`trend-d ${d > 0 ? "up" : "down"}`}>
                    {" "}{d > 0 ? "▲" : "▼"} {s.unit ? fmtNumber(Math.abs(d), 0) : Math.abs(d).toFixed(2)}
                  </span>
                )}
              </span>
            </div>
            {pts.length > 1 ? (
              <>
                <Sparkline points={pts} unit={s.unit} />
                <div className="trend-axis"><span>{shortPeriod(pts[0].period)}</span><span>{shortPeriod(last.period)}</span></div>
              </>
            ) : (
              <p className="dlg-muted">Only one issue so far ({last.period}); the trend starts with the next issue.</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
