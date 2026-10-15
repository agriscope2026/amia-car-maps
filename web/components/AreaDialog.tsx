"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { CropsLayer, Gazetteer, Layer, Payload, ProductType } from "@/lib/types";
import { fmtDate, fmtNumber, fmtValue } from "@/lib/format";
import { changeMeaning, enviParts, layerBreaks, type Change, type TrendPoint } from "@/lib/insights";
import { FarmAdvice } from "./FarmAdvice";
import { EnviBar, Trends } from "./Insights";

const ENVI_ROWS: [string, string, (v: number) => string][] = [
  ["envi", "ENVI value", (v) => v.toFixed(3)],
  ["rank", "Rank (of 77)", (v) => `#${v}`],
  ["hazard_raw", "Drought forecast score", (v) => fmtNumber(v, 0)],
  ["damage_raw", "Historical damage (mean)", (v) => `${fmtNumber(v)} ha/yr`],
  ["crops_raw", "Standing crops", (v) => `${fmtNumber(v)} ha`],
  ["hazard_norm", "Drought (normalized)", (v) => v.toFixed(2)],
  ["damage_norm", "Damage (normalized)", (v) => v.toFixed(2)],
  ["crops_norm", "Crops (normalized)", (v) => v.toFixed(2)],
];

/** "October 5" → "Oct 5", "November 2026" → "Nov 2026", other labels unchanged. */
function shortLabel(label: string): string {
  const m = label.match(/^([A-Z][a-z]+) (\d{1,2}|\d{4})$/);
  return m ? `${m[1].slice(0, 3)} ${m[2]}` : label;
}

/** Recommendation lines that name this municipality or its province (shown first in the dialog). */
function localLines(text: string, name: string, province: string): string[] {
  const n = name.replace(/ City$/, "").toLowerCase();
  const p = province.toLowerCase();
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l && (l.toLowerCase().includes(n) || l.toLowerCase().includes(p)));
}

export default function AreaDialog({ areaKey, geo, payload, layer, crops, change, compared, onLayer, onPhoto, onClose }: {
  areaKey: string;
  geo: Gazetteer;
  payload: Payload | null;
  layer: Layer | null;
  crops: CropsLayer | null;
  change?: Change; // class change since the previous issue (on the compared layer)
  compared?: { layer: string; issue: string } | null; // what was compared, null when there is no previous issue
  onLayer: (id: string) => void;
  onPhoto?: () => void;
  onClose: () => void;
}) {
  const g = geo.gazetteer.find((x) => x.area_key === areaKey);
  const name = g?.name ?? areaKey;
  const province = g?.province ?? "";
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    box.current?.focus();
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  const v = layer?.values[areaKey];
  const desc = layer?.legend.classes.find((c) => c.label === v?.class)?.desc;
  const series = useMemo(() => payload?.layers.filter((l) => /^(d_|m_)/.test(l.id)) ?? [], [payload]);
  const cropRows = crops ? crops.crops.map((c) => [c, crops.values[areaKey]?.[c] ?? 0] as [string, number]).filter(([, ha]) => ha > 0) : [];
  const cropMax = Math.max(1, ...cropRows.map(([, ha]) => ha));
  const recs = layer?.recommendations ?? payload?.texts.recommendations ?? ""; // ENVI month: its own
  const local = localLines(recs, name, province);
  const t = payload?.texts;
  // ENVI: the map on screen (season or one month) explains itself
  const enviV = payload?.type === "envi" ? (layer ?? payload.layers[0])?.values[areaKey] : undefined;
  const enviWhen = payload?.type === "envi" && layer?.id.startsWith("m_") ? ` in ${layer.label}` : "";
  const parts = enviParts(enviV, payload?.method?.weights);
  const m = payload ? changeMeaning(payload.type) : null;

  // this area over past issues (ENVI, 10-day and season rainfall)
  const [history, setHistory] = useState<Partial<Record<ProductType, TrendPoint[]>> | null>(null);
  useEffect(() => {
    let cancelled = false;
    setHistory(null);
    fetch(`/api/public/history?area=${encodeURIComponent(areaKey)}`)
      .then((r) => (r.ok ? r.json() : { series: {} }))
      .then((d) => !cancelled && setHistory(d.series ?? {}))
      .catch(() => !cancelled && setHistory({}));
    return () => {
      cancelled = true;
    };
  }, [areaKey]);
  const brief = (q: string) => `/brief?product=${encodeURIComponent(payload?.id ?? "")}${layer ? `&layer=${encodeURIComponent(layer.id)}` : ""}&${q}`;

  return (
    <div className="dlg-backdrop" onClick={onClose}>
      <div
        className="dlg"
        role="dialog"
        aria-modal="true"
        aria-labelledby="dlg-title"
        ref={box}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="dlg-head">
          <div>
            <h2 id="dlg-title">{name}</h2>
            <p>
              {province}
              {g?.psgc ? ` · PSGC ${g.psgc}` : ""}
            </p>
          </div>
          <button className="dlg-close" onClick={onClose} aria-label="Close (Esc)">
            ✕
          </button>
        </header>

        <div className="dlg-body">
          {payload && layer && (
            <section className="dlg-card dlg-value" data-tour="area-value">
              <div className="dlg-kicker">
                {payload.texts.title} · {layer.label}
              </div>
              <div className="dlg-big">{fmtValue(v, layer)}</div>
              {v && v.class !== "No data" && (
                <div className="dlg-class">
                  <span className="sw" style={{ background: v.color }} />
                  {typeof v.value === "number" && layer.legend.kind === "graduated" ? `${v.class}${layer.unit === "mm" ? " mm" : ""}` : v.class}
                  {desc && <strong> · {desc}</strong>}
                </div>
              )}
              <div className="dlg-muted">
                {payload.period.label} · as of {fmtDate(payload.issued)}
              </div>
              {compared && m && (
                <div className="dlg-change">
                  {change ? (
                    <span style={{ color: change.dir > 0 ? m.upColor : m.downColor }}>
                      {change.dir > 0 ? "▲" : "▼"} {change.dir > 0 ? "Up" : "Down"} from <strong>{change.from}</strong> to <strong>{change.to}</strong> ({change.dir > 0 ? m.up : m.down})
                    </span>
                  ) : (
                    <span>● No change in class</span>
                  )}
                  <span className="dlg-muted"> since the {compared.issue} issue{compared.layer !== layer.label ? ` · ${compared.layer}` : ""}</span>
                </div>
              )}
            </section>
          )}

          {enviV && parts && typeof enviV.envi === "number" && (
            <section className="dlg-card">
              <h3>Why is {name} {enviV.class}{enviWhen}?</h3>
              <EnviBar name={name} cls={enviV.class} envi={enviV.envi} parts={parts} breaks={layerBreaks(layer, payload?.method?.breaks)} />
            </section>
          )}

          {series.length > 1 && (
            <section className="dlg-card">
              <h3>{series[0].id.startsWith("d_") ? "Day by day" : "Month by month"}</h3>
              <div className="dlg-series">
                {series.map((l) => {
                  const x = l.values[areaKey];
                  return (
                    <button key={l.id} className={l.id === layer?.id ? "on" : ""} onClick={() => onLayer(l.id)} title={`Show ${l.label} on the map`}>
                      <span className="dlg-chip" style={{ background: x?.color ?? "#d9d9d9" }} />
                      <span className="dlg-s-label">{shortLabel(l.label)}</span>
                      <span className="dlg-s-val">
                        {typeof x?.envi === "number" ? x.envi.toFixed(2) : typeof x?.value === "number" ? `${fmtNumber(x.value, 0)}${l.unit === "%" ? "%" : ""}` : x?.value ?? "–"}
                      </span>
                    </button>
                  );
                })}
              </div>
              {payload?.type === "rainfall_seasonal" && typeof v?.pct_normal === "number" && (
                <p className="dlg-muted">Season: {fmtNumber(v.pct_normal as number, 0)}% of normal</p>
              )}
            </section>
          )}

          {payload?.type === "envi" && v && (
            <section className="dlg-card">
              <h3>Vulnerability indicators</h3>
              <table className="dlg-table">
                <tbody>
                  {ENVI_ROWS.filter(([k]) => typeof v[k] === "number").map(([k, label, f]) => (
                    <tr key={k}>
                      <th>{label}</th>
                      <td>{f(v[k] as number)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          <section className="dlg-card">
            <h3>Trend over past issues</h3>
            <Trends series={history} />
          </section>

          {cropRows.length > 0 && (
            <section className="dlg-card">
              <h3>Standing crops <span className="dlg-muted">(as of {crops?.as_of})</span></h3>
              <ul className="dlg-crops">
                {cropRows.map(([c, ha]) => (
                  <li key={c}>
                    <span className="dlg-crop-name">
                      <span className="dot" style={{ background: crops?.colors?.[c] }} />
                      {c}
                    </span>
                    <span className="dlg-bar">
                      <span style={{ width: `${(ha / cropMax) * 100}%`, background: crops?.colors?.[c] }} />
                    </span>
                    <span className="dlg-ha">{fmtNumber(ha)} ha</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {t && (t.advice_rice || t.advice_corn || t.advice_hvc || t.advice_livestock) && (
            <div className="dlg-card dlg-farm">
              <FarmAdvice texts={t} />
            </div>
          )}

          {recs && (
            <section className="dlg-card" data-tour="area-recs">
              <h3>Recommendations</h3>
              {local.length > 0 && (
                <div className="dlg-local">
                  <div className="dlg-kicker">For {name} / {province}</div>
                  {local.map((l, i) => (
                    <p key={i}>{l.replace(/^[-•\d.\s]+/, "")}</p>
                  ))}
                </div>
              )}
              <details open={!local.length}>
                <summary>{local.length ? "All recommendations" : "Recommendations for CAR"}</summary>
                <div className="prose recs">
                  {recs
                    .split("\n")
                    .filter((l) => l.trim())
                    .map((line, i) => (
                      <p key={i} className={/^\s*\d+\./.test(line) ? "num" : /^\s*[-•]/.test(line) ? "li" : "head"}>
                        {line.replace(/^\s*[-•]\s*/, "")}
                      </p>
                    ))}
                </div>
              </details>
            </section>
          )}
          {!payload && <p className="muted">Choose a map to see the forecast for {name}.</p>}
        </div>

        <footer className="dlg-foot">
          {payload?.id && (
            <>
              <a className="btn secondary" href={brief(`area=${encodeURIComponent(areaKey)}`)} target="_blank" rel="noopener">
                📄 Brief: {name}
              </a>
              {province && (
                <a className="btn secondary" href={brief(`province=${encodeURIComponent(province)}`)} target="_blank" rel="noopener">
                  📄 Brief: {province}
                </a>
              )}
            </>
          )}
          {onPhoto && (
            <button className="btn secondary" onClick={onPhoto}>
              🖼 Open the map images
            </button>
          )}
          <button className="btn" onClick={onClose}>
            Close
          </button>
        </footer>
      </div>
    </div>
  );
}
