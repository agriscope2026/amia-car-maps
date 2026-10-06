import type { Download } from "@/lib/types";

const SHORT: Record<string, string> = {
  png: "PNG", pdf: "PDF", presentation: "Presentation PNG", presentation_pdf: "Presentation PDF",
  poster: "A4 poster PNG", poster_pdf: "A4 poster PDF", zip: "ZIP",
};

/** Map images and PDFs: one row per map (the map on screen highlighted), then a ZIP with all of them. */
export function Downloads({ items, currentLayer }: { items: Download[]; currentLayer?: string }) {
  const visible = items.filter((d) => !d.preview);
  const groups = new Map<string, Download[]>();
  for (const d of visible) {
    if (d.group === "Whole product") continue;
    const g = d.group ?? d.label;
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g)!.push(d);
  }
  const zip = visible.find((d) => d.kind === "zip");
  const href = (d: Download) => d.url ?? d.path;
  return (
    <div className="dl">
      <ul className="dl-rows">
        {[...groups.entries()].map(([label, files]) => (
          <li key={label} className={files.some((f) => f.layer === currentLayer) ? "on" : ""}>
            <span className="dl-name">{label}</span>
            <span className="dl-links">
              {files.map((f) => (
                <a key={f.kind} href={href(f)} download title={f.label}>
                  ⤓ {SHORT[f.kind ?? ""] ?? f.label}
                </a>
              ))}
            </span>
          </li>
        ))}
      </ul>
      {zip && (
        <a className="btn dl-zip" href={href(zip)} download>
          ⤓ {zip.label}
        </a>
      )}
    </div>
  );
}
