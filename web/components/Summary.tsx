import type { CropsLayer, Layer, Payload } from "@/lib/types";
import { fmtNumber } from "@/lib/format";

interface Area {
  key: string;
  value: number;
}

type Names = Record<string, string>;

function numericAreas(layer: Layer): Area[] {
  return Object.entries(layer.values)
    .filter(([, v]) => typeof v.value === "number")
    .map(([key, v]) => ({ key, value: v.value as number }));
}

function nameOf(payload: Payload, key: string) {
  const [prov, mun] = key.split("|");
  const t = (s: string) => s.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
  return `${t(mun ?? prov)} (${t(prov)})`;
}

function ClassBars({ layer }: { layer: Layer }) {
  const items = layer.legend.classes;
  const max = Math.max(1, ...items.map((c) => c.count ?? 0));
  return (
    <ul className="bars" aria-label="Municipalities per class">
      {items.map((c) => (
        <li key={c.label}>
          <span className="bar-label">{c.label}</span>
          <span className="bar-track">
            <span className="bar" style={{ width: `${((c.count ?? 0) / max) * 100}%`, background: c.color }} />
          </span>
          <span className="count">{c.count ?? 0}</span>
        </li>
      ))}
    </ul>
  );
}

export function Summary({ payload, layer, crops, names }: { payload: Payload; layer: Layer; crops: CropsLayer | null; names: Names }) {
  if (payload.type === "envi") {
    // from the layer on screen: the season ENVI or one month's
    const rows = Object.entries(layer.values).filter(([, v]) => typeof v.envi === "number");
    const risk = rows.filter(([, v]) => v.class === "High" || v.class === "Very High");
    const cropsAtRisk = risk.reduce((s, [, v]) => s + (typeof v.crops_raw === "number" ? v.crops_raw : 0), 0);
    const top = [...rows].sort((a, b) => (b[1].envi as number) - (a[1].envi as number)).slice(0, 10);
    return (
      <div className="summary">
        {layer.id.startsWith("m_") && <p className="hint">{layer.label}: drought forecast of this month only.</p>}
        <div className="cards">
          <div className="card risk">
            <div className="big">{fmtNumber(cropsAtRisk, 0)} ha</div>
            <div>standing crops in High + Very High areas</div>
          </div>
          <div className="card">
            <div className="big">{risk.length}</div>
            <div>municipalities High or Very High</div>
          </div>
        </div>
        <ClassBars layer={layer} />
        <h3>Most vulnerable areas</h3>
        <ol className="top">
          {top.map(([k, v]) => (
            <li key={k}>
              <span>{names[k] ?? nameOf(payload, k)}</span>
              <span className="pill" style={{ background: v.color }}>
                {(v.envi as number).toFixed(3)} · {v.class}
              </span>
            </li>
          ))}
        </ol>
      </div>
    );
  }

  if (payload.type === "drought") {
    const by = payload.summary.by_month_province as Record<string, Record<string, string>>;
    const months = payload.period.months ?? Object.keys(by);
    const provs = Object.keys(by[months[0]] ?? {}).sort();
    const colors = Object.fromEntries(layer.legend.classes.map((c) => [c.label, c.color]));
    return (
      <div className="summary">
        <ClassBars layer={layer} />
        <h3>Province outlook by month</h3>
        <div className="table-scroll">
          <table className="matrix">
            <thead>
              <tr>
                <th scope="col">Province</th>
                {months.map((m) => (
                  <th key={m} scope="col">
                    {new Date(`${m}-01T00:00:00`).toLocaleString("en", { month: "short" })}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {provs.map((p) => (
                <tr key={p}>
                  <th scope="row">{p}</th>
                  {months.map((m) => (
                    <td key={m} style={{ background: colors[by[m][p]] }} title={`${p}, ${m}: ${by[m][p]}`}>
                      <span className="sr-only">{by[m][p]}</span>
                      <span aria-hidden>{(by[m][p] ?? "").split(" ").map((w) => w[0]).join("")}</span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint">N = not affected, DC = dry condition, DS = dry spell, D = drought.</p>
      </div>
    );
  }

  // rainfall (mm / %)
  const areas = numericAreas(layer);
  if (!areas.length) return <p className="muted">No values for this layer.</p>;
  const sorted = [...areas].sort((a, b) => b.value - a.value);
  const mean = areas.reduce((a, b) => a + b.value, 0) / areas.length;
  const u = layer.unit === "%" ? "%" : ` ${layer.unit}`;
  let cropNote = null;
  if (crops && layer.unit === "mm") {
    const limit = layer.id.startsWith("d_") ? 5 : layer.id === "total" ? 25 : 100;
    const dry = areas.filter((a) => a.value < limit);
    const rice = dry.reduce((s, a) => s + (crops.values[a.key]?.Rice ?? 0), 0);
    const corn = dry.reduce((s, a) => s + (crops.values[a.key]?.Corn ?? 0), 0);
    if (dry.length)
      cropNote = (
        <div className="card">
          <div className="big">{fmtNumber(rice + corn, 0)} ha</div>
          <div>
            rice + corn standing in {dry.length} areas with &lt; {limit} mm
          </div>
        </div>
      );
  }
  return (
    <div className="summary">
      <div className="cards">
        <div className="card">
          <div className="big">
            {fmtNumber(sorted[sorted.length - 1].value, 0)}–{fmtNumber(sorted[0].value, 0)}
            {u}
          </div>
          <div>range across {areas.length} municipalities (mean {fmtNumber(mean, 0)}{u})</div>
        </div>
        {cropNote}
      </div>
      <ClassBars layer={layer} />
      <div className="two">
        <div>
          <h3>Highest</h3>
          <ol className="top">
            {sorted.slice(0, 5).map((a) => (
              <li key={a.key}>
                <span>{names[a.key] ?? a.key}</span>
                <span>{fmtNumber(a.value)}{u}</span>
              </li>
            ))}
          </ol>
        </div>
        <div>
          <h3>Lowest</h3>
          <ol className="top">
            {sorted.slice(-5).reverse().map((a) => (
              <li key={a.key}>
                <span>{names[a.key] ?? a.key}</span>
                <span>{fmtNumber(a.value)}{u}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}
