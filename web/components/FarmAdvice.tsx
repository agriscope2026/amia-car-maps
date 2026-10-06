import { FARM_CROPS, type Texts } from "@/lib/types";

/** Farm recommendations for rice, corn and high-value crops (10-day, seasonal and drought products). */
export function FarmAdvice({ texts }: { texts: Texts }) {
  const items = FARM_CROPS.filter((c) => (texts[c.key] ?? "").trim());
  if (!items.length) return null;
  return (
    <section className="group" id="farm">
      <h2>Farm recommendations</h2>
      <ul className="farm">
        {items.map((c) => (
          <li key={c.key}>
            <span className="chip" style={{ background: c.color }}>
              {c.crop.toUpperCase()}
            </span>
            <span>{texts[c.key]}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
