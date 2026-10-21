"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Download, Payload } from "@/lib/types";
import { fmtDate } from "@/lib/format";
import ZoomImage from "./ZoomImage";
import { FarmAdvice } from "./FarmAdvice";

export interface Photo {
  id: string;
  layer?: string; // map layer the photo belongs to (rainfall/drought: one photo per map)
  label: string;
  src: string;
  alt: string;
  pkg?: string;
  print?: string;
}

const href = (d?: Download) => d?.url ?? d?.path;

export type PhotoView = "landscape" | "portrait";

/** Rainfall / drought report pages around the maps (not map layers): title first, summary and recommendations last. */
const PAGE_RE = /^(a4|cover|advisory|summary|recommendations|crops)(?:_(\d+))?$/;
// a4: the one-page A4 (print format) of the tropical cyclone outlook; advisory: its main Facebook post; crops: its
// crop and livestock advice post
const PAGE_RANK = { a4: 0, cover: 1, advisory: 2, summary: 3, recommendations: 4, crops: 5 } as const;
const isPage = (id: string) => PAGE_RE.test(id);

/** Report pages of a product (title first, then summary and recommendations pages in order), from its downloads:
 * long summaries / recommendations continue on extra pages (summary_2, recommendations_2, …). */
function pageIds(dl: Download[]): { first: string[]; last: string[] } {
  const ids = [...new Set(dl.map((d) => d.layer ?? "").filter(isPage))];
  const rank = (id: string) => {
    const m = id.match(PAGE_RE)!;
    return PAGE_RANK[m[1] as keyof typeof PAGE_RANK] * 1000 + Number(m[2] ?? 1);
  };
  ids.sort((a, b) => rank(a) - rank(b));
  // before the maps: A4 page, title, advisory; after them: summary and recommendations
  return { first: ids.filter((i) => rank(i) < 3000), last: ids.filter((i) => rank(i) >= 3000) };
}

/**
 * Photos for photo mode.
 *  - ENVI: title page, season outlook, each month's ENVI, summary and recommendations – as the landscape
 *    presentation or the portrait A4 poster (`view`), falling back to the print map when neither was generated.
 *  - Other products: one finished print map per day / month / layer.
 */
export function photosOf(payload: Payload | null, view: PhotoView = "landscape"): Photo[] {
  const dl = payload?.downloads ?? [];
  if (!payload || !dl.length) return [];
  const pick = (files: Download[], ...kinds: string[]) => kinds.map((k) => files.find((d) => d.kind === k)).find(Boolean);
  if (payload.type === "envi" || payload.type === "tc_advisory") {
    const out: Photo[] = [];
    const tc = payload.type === "tc_advisory";
    // ENVI: title page, season outlook, each month, summary, recommendations; tropical cyclone: title page, advisory,
    // map, summary, recommendations – in the chosen format (ENVI: presentation / A4; tropical cyclone: Facebook / A4)
    const maps = tc ? payload.layers : payload.layers.filter((x) => x.id === "envi" || x.id.startsWith("m_"));
    const labels = new Map(maps.map((l) => [l.id, l.id === "envi" ? `Season outlook (${payload.period.label})` : l.label]));
    const [web, full, pdf] = view === "portrait" ? ["poster_web", "poster", "poster_pdf"]
      : tc ? ["social_web", "social", "social"] : ["presentation_web", "presentation", "presentation_pdf"];
    const pg = pageIds(dl);
    for (const id of [...pg.first, ...maps.map((l) => l.id), ...pg.last]) {
      const files = dl.filter((d) => d.layer === id);
      const img = pick(files, web, full, "jpg", "png");
      if (!img) continue;
      const page = isPage(id);
      const label = page ? img.group ?? id : labels.get(id) ?? id;
      out.push({ id, layer: page ? undefined : id, label, src: href(img)!, alt: img.alt ?? `ENVI ${label}`,
        pkg: href(pick(files, full, "png")), print: href(pick(files, pdf, "pdf")) });
    }
    return out;
  }
  const by = new Map<string, Download[]>();
  for (const d of dl) if (d.layer) by.set(d.layer, [...(by.get(d.layer) ?? []), d]);
  const out: Photo[] = [];
  // title page first, then one map per day / month, then the summary and recommendations pages
  const labels = new Map(payload.layers.map((l) => [l.id, l.label]));
  const pg = pageIds(dl);
  for (const id of [...pg.first, ...payload.layers.map((l) => l.id), ...pg.last]) {
    const files = by.get(id) ?? [];
    const img = pick(files, "jpg", "png");
    if (!img) continue;
    const page = isPage(id);
    const label = page ? img.group ?? id : labels.get(id) ?? id;
    out.push({ id, layer: page ? undefined : id, label, src: href(img)!, alt: img.alt ?? label,
      pkg: href(pick(files, "png")), print: href(pick(files, "pdf")) });
  }
  return out;
}

/** Full-screen view of the finished images (zoomable) with the recommendations beside them. */
export default function PhotoMode({ payload, layerId, onLayer, onClose }: {
  payload: Payload;
  layerId?: string;
  onLayer: (id: string) => void;
  onClose: () => void;
}) {
  // ENVI: landscape presentation or portrait A4 poster, for the season outlook and every month
  // phones: the portrait A4 version fits the screen and stays readable without zooming
  const [view, setView] = useState<PhotoView>(() =>
    typeof window !== "undefined" && window.matchMedia("(max-width: 820px)").matches ? "portrait" : "landscape",
  );
  const tc = payload.type === "tc_advisory";
  const hasPosters = (payload.type === "envi" || tc) && (payload.downloads ?? []).some((d) => d.kind === "poster_web" || d.kind === "poster");
  const photos = useMemo(() => photosOf(payload, view), [payload, view]);
  // the photo on screen: a map follows the dashboard's layer; a page (title, summary, recommendations) is kept here
  const [page, setPage] = useState<string | null>(null);
  useEffect(() => setPage(null), [layerId]);
  // details (downloads, recommendations): beside the photo on wide screens, folded away elsewhere so the photo gets the room
  const [details, setDetails] = useState(true);
  useEffect(() => {
    if (window.matchMedia("(max-width: 1100px), (max-height: 520px)").matches) setDetails(false);
  }, []);
  const pageIdx = page ? photos.findIndex((p) => p.id === page) : -1;
  const idx = pageIdx >= 0 ? pageIdx : Math.max(0, photos.findIndex((p) => p.layer === layerId));
  const cur = photos[idx];
  const dialog = useRef<HTMLDivElement>(null);
  const select = useCallback(
    (i: number) => {
      const p = photos[(i + photos.length) % photos.length];
      if (!p) return;
      if (p.layer) {
        setPage(null);
        onLayer(p.layer);
      } else setPage(p.id);
    },
    [photos, onLayer],
  );

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (details && window.matchMedia("(max-width: 820px)").matches) setDetails(false);
        else onClose();
      }
      else if (e.key === "ArrowRight") select(idx + 1);
      else if (e.key === "ArrowLeft") select(idx - 1);
    };
    window.addEventListener("keydown", key);
    dialog.current?.focus();
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", key);
      document.body.style.overflow = prev;
    };
  }, [select, idx, onClose, details]);

  useEffect(() => {
    for (const d of [-1, 1]) {
      const p = photos[(idx + d + photos.length) % photos.length];
      if (p) new Image().src = p.src;
    }
  }, [idx, photos]);

  const t = payload.texts;
  // a month of ENVI has its own recommendations (its forecast, its High / Very High areas)
  const layerRecs = payload.layers.find((l) => l.id === cur?.layer)?.recommendations;
  const recs = (layerRecs ?? t.recommendations ?? "").split("\n").filter((l) => l.trim());

  return (
    <div className="photo" role="dialog" aria-modal="true" aria-label={`Photo mode – ${t.title}`} ref={dialog} tabIndex={-1}>
      <header className="photo-bar">
        <div className="photo-title">
          <strong>{t.title}</strong>
          <span>
            {payload.period.label} · as of {fmtDate(payload.issued)}
          </span>
        </div>
        {photos.length > 1 && (
          <span className="photo-count">
            {idx + 1} / {photos.length}
          </span>
        )}
        {hasPosters && (
          <div className="photo-view" role="radiogroup" aria-label="Image format">
            {(["landscape", "portrait"] as const).map((v) => (
              <button key={v} role="radio" aria-checked={view === v} className={`photo-btn ${view === v ? "on" : ""}`} onClick={() => setView(v)}
                title={v === "landscape" ? (tc ? "Facebook post (4:5)" : "Presentation (landscape)") : (tc ? "Print format (A4 page)" : "A4 poster (portrait)")}>
                {v === "landscape" ? (tc ? "f" : "▭") : "▯"}<span className="photo-btn-label"> {v === "landscape" ? (tc ? "Facebook" : "Presentation") : (tc ? "Print format" : "A4")}</span>
              </button>
            ))}
          </div>
        )}
        {cur && (
          <a className="photo-btn" href={cur.pkg ?? cur.print ?? cur.src} download title={cur.pkg ? "Download PNG (high definition)" : "Download image"}>
            ⤓<span className="photo-btn-label"> Download</span>
          </a>
        )}
        <button className={`photo-btn ${details ? "on" : ""}`} onClick={() => setDetails((d) => !d)} aria-expanded={details} aria-controls="photo-side">
          ☰<span className="photo-btn-label"> {details ? "Hide details" : "Details"}</span>
        </button>
        <button className="photo-close" onClick={onClose} aria-label="Close photo mode (Esc)">
          ✕<span className="photo-btn-label"> Close</span>
        </button>
      </header>

      <div className={`photo-body ${details ? "with-side" : ""}`}>
        <figure className="photo-stage">
          {cur ? (
            <>
              <ZoomImage src={cur.src} alt={cur.alt} />
              {photos.length > 1 && (
                <>
                  <button className="photo-nav prev" onClick={() => select(idx - 1)} aria-label="Previous image">‹</button>
                  <button className="photo-nav next" onClick={() => select(idx + 1)} aria-label="Next image">›</button>
                </>
              )}
              <figcaption>{cur.label}</figcaption>
            </>
          ) : (
            <p className="muted">The images of this product have not been generated yet.</p>
          )}
        </figure>

        <aside className="photo-side" id="photo-side" hidden={!details}>
          <button className="photo-side-close" onClick={() => setDetails(false)}>Hide details ▾</button>
          {cur && (
            <div className="row">
              <a className="btn" href={cur.pkg ?? cur.print ?? cur.src} download>
                ⤓ {cur.pkg ? "PNG (high definition)" : "Download image"}
              </a>
              {cur.pkg && cur.print && (
                <a className="btn secondary" href={cur.print} download>
                  ⤓ PDF
                </a>
              )}
            </div>
          )}
          <FarmAdvice texts={t} />
          {recs.length > 0 && (
            <section>
              <h2>Agricultural recommendations</h2>
              <div className="prose recs">
                {recs.map((line, i) => (
                  <p key={i} className={/^\s*\d+\./.test(line) ? "num" : /^\s*[-•]/.test(line) ? "li" : "head"}>
                    {line.replace(/^\s*[-•]\s*/, "")}
                  </p>
                ))}
              </div>
            </section>
          )}
          {t.notes && (
            <section>
              <h2>Notes</h2>
              <p className="prose small">{t.notes}</p>
            </section>
          )}
          <p className="small muted">{t.disclaimer}</p>
          <p className="small muted">Sources: {t.sources}</p>
        </aside>
      </div>

      {photos.length > 1 && (
        <nav className="photo-strip" aria-label="Images">
          {photos.map((p, i) => (
            <button key={p.id} className={i === idx ? "on" : ""} onClick={() => select(i)} aria-current={i === idx}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={p.src} alt="" loading="lazy" />
              <span>{p.label.replace(/ \(.*\)$/, "")}</span>
            </button>
          ))}
        </nav>
      )}
    </div>
  );
}
