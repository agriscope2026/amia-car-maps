import type { CropsLayer, Layer } from "@/lib/types";
import { IRRIGATION_TYPES, cropBreaks, fmtNumber, legendLabel } from "@/lib/format";
import { cropRamp } from "@/lib/crops";

export function Legend({ layer, compact = false }: { layer: Layer; compact?: boolean }) {
  const lg = layer.legend;
  const unitTitle =
    lg.unit === "mm" ? "Rainfall in millimetres (mm)" : lg.unit === "%" ? "Percent of normal rainfall" : lg.title;
  return (
    <div className={`legend ${compact ? "compact" : ""}`}>
      <div className="legend-title">{compact ? layer.label : unitTitle}</div>
      {compact && <div className="legend-sub">{unitTitle}</div>}
      <ul>
        {lg.classes.map((c) => (
          <li key={c.label}>
            <span className="sw" style={{ background: c.color }} aria-hidden />
            <span>
              {legendLabel(c.label, lg.unit, lg.kind)}
              {c.desc && <span className="desc"> {c.desc}</span>}
            </span>
            {!compact && c.count !== undefined && <span className="count">{c.count}</span>}
          </li>
        ))}
        {(lg.no_data.count ?? 0) > 0 && (
          <li>
            <span className="sw hatch" aria-hidden />
            <span>No data</span>
            {!compact && <span className="count">{lg.no_data.count}</span>}
          </li>
        )}
      </ul>
      {!compact && <p className="hint">Numbers = municipalities per class.</p>}
    </div>
  );
}

/** Crop overlay controls + legend: a checkbox per crop (circles: several, choropleth: one) and the size/colour key. */
export function CropLegend({ crops, sel, mode, onChange }: {
  crops: CropsLayer;
  sel: string[];
  mode: string;
  onChange: (sel: string[]) => void;
}) {
  const colors = crops.colors ?? {};
  const totals = Object.fromEntries(
    crops.crops.map((c) => [c, Object.values(crops.values).reduce((s, v) => s + (v[c] ?? 0), 0)]),
  );
  const toggle = (c: string) => {
    if (mode === "choropleth") return onChange([c]);                 // one crop at a time
    onChange(sel.includes(c) ? sel.filter((x) => x !== c) : [...sel, c]);
  };
  const max = Math.max(0, ...Object.values(crops.values).flatMap((v) => sel.map((c) => v[c] ?? 0)));
  const first = sel[0];
  const br = first ? cropBreaks(Object.values(crops.values).map((v) => v[first] ?? 0)) : [];
  const ramp = first ? cropRamp(colors[first] ?? "#2e7d32") : [];
  return (
    <div className="legend">
      <p className="hint">
        {mode === "choropleth" ? "Choose one crop." : "Tick one or more crops."} Standing area as of {crops.as_of}.
      </p>
      <ul className="crop-list">
        {crops.crops.map((c) => (
          <li key={c}>
            <label className="check">
              <input type={mode === "choropleth" ? "radio" : "checkbox"} name="crop-pick" checked={sel.includes(c)} onChange={() => toggle(c)} />
              <span className="dot" style={{ background: colors[c] }} aria-hidden />
              {c}
              <span className="count">{fmtNumber(totals[c], 0)} ha</span>
            </label>
          </li>
        ))}
      </ul>
      {sel.length > 0 && mode === "circles" && max > 0 && (
        <div className="circles">
          {[max, max / 4, max / 16].map((v) => (
            <span key={v} className="circle-item">
              <span className="circle" style={{ width: Math.sqrt(v / max) * 52, height: Math.sqrt(v / max) * 52, background: "rgba(120,120,120,.25)", borderColor: "#444" }} />
              {fmtNumber(v, 0)} ha
            </span>
          ))}
        </div>
      )}
      {first && mode === "choropleth" && (
        <ul>
          {ramp.map((c, i) => (
            <li key={c}>
              <span className="sw" style={{ background: c }} />
              <span>
                {i === 0 ? `< ${fmtNumber(br[0], 0)}` : i === ramp.length - 1 ? `≥ ${fmtNumber(br[i - 1], 0)}` : `${fmtNumber(br[i - 1], 0)}–${fmtNumber(br[i], 0)}`} ha
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function IrrigationLegend({ types, data, onToggle }: { types: string[]; data: any; onToggle: (t: string) => void }) {
  const counts: Record<string, number> = {};
  for (const f of data?.features ?? []) counts[f.properties.type] = (counts[f.properties.type] ?? 0) + 1;
  return (
    <div className="legend">
      {data?.synthetic && <p className="hint warn">Demo records – approximate, synthetic locations.</p>}
      <ul>
        {Object.entries(IRRIGATION_TYPES).map(([k, t]) => (
          <li key={k}>
            <label className="check">
              <input type="checkbox" checked={types.includes(k)} onChange={() => onToggle(k)} />
              <span className="dot" style={{ background: t.color }} aria-hidden />
              {t.label}
              <span className="count">{counts[k] ?? 0}</span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
