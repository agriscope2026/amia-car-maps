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

/**
 * Photos for photo mode.
 *  - ENVI: the season outlook first, then each month's ENVI – as the landscape presentation or the portrait A4
 *    poster (`view`), falling back to the print map when neither was generated.
 *  - Other products: one finished print map per day / month / layer.
 */
export function photosOf(payload: Payload | null, view: PhotoView = "landscape"): Photo[] {
  const dl = payload?.downloads ?? [];
  if (!payload || !dl.length) return [];
  const pick = (files: Download[], ...kinds: string[]) => kinds.map((k) => files.find((d) => d.kind === k)).find(Boolean);
  if (payload.type === "envi") {
    const out: Photo[] = [];
    for (const l of payload.layers.filter((x) => x.id === "envi" || x.id.startsWith("m_"))) {
      const files = dl.filter((d) => d.layer === l.id);
      const [web, full, pdf] = view === "portrait" ? ["poster_web", "poster", "poster_pdf"] : ["presentation_web", "presentation", "presentation_pdf"];
      const img = pick(files, web, full, "jpg", "png");
      if (!img) continue;
      const label = l.id === "envi" ? `Season outlook (${payload.period.label})` : l.label;
      out.push({ id: l.id, layer: l.id, label, src: href(img)!, alt: img.alt ?? `ENVI ${label}`,
        pkg: href(pick(files, full, "png")), print: href(pick(files, pdf, "pdf")) });
    }
    return out;
  }
  const by = new Map<string, Download[]>();
  for (const d of dl) if (d.layer) by.set(d.layer, [...(by.get(d.layer) ?? []), d]);
  const out: Photo[] = [];
  for (const l of payload.layers) {
    const files = by.get(l.id) ?? [];
    const img = pick(files, "jpg", "png");
    if (!img) continue;
    out.push({ id: l.id, layer: l.id, label: l.label, src: href(img)!, alt: img.alt ?? l.label,
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
  const [view, setView] = useState<PhotoView>("landscape");
  const hasPosters = payload.type === "envi" && (payload.downloads ?? []).some((d) => d.kind === "poster_web" || d.kind === "poster");
  const photos = useMemo(() => photosOf(payload, view), [payload, view]);
  const byLayer = photos.some((p) => p.layer);
  const [own, setOwn] = useState(0); // index for photos that are not tied to a map layer (ENVI)
  // details (downloads, recommendations): beside the photo on wide screens, folded away elsewhere so the photo gets the room
  const [details, setDetails] = useState(true);
  useEffect(() => {
    if (window.matchMedia("(max-width: 1100px), (max-height: 520px)").matches) setDetails(false);
  }, []);
  const idx = byLayer ? Math.max(0, photos.findIndex((p) => p.layer === layerId)) : Math.min(own, photos.length - 1);
  const cur = photos[idx];
  const dialog = useRef<HTMLDivElement>(null);
  const select = useCallback(
    (i: number) => {
      const p = photos[(i + photos.length) % photos.length];
      if (!p) return;
      if (p.layer) onLayer(p.layer);
      else setOwn((i + photos.length) % photos.length);
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
                title={v === "landscape" ? "Presentation (landscape)" : "A4 poster (portrait)"}>
                {v === "landscape" ? "▭" : "▯"}<span className="photo-btn-label"> {v === "landscape" ? "Presentation" : "A4"}</span>
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
