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

/**
 * Photos for photo mode.
 *  - ENVI: only the presentation images – the 1920×1080 presentation (infographic with recommendations) and the
 *    A4 poster.
 *  - Other products: one finished print map per day / month / layer.
 */
export function photosOf(payload: Payload | null): Photo[] {
  const dl = payload?.downloads ?? [];
  if (!payload || !dl.length) return [];
  const pick = (files: Download[], ...kinds: string[]) => kinds.map((k) => files.find((d) => d.kind === k)).find(Boolean);
  if (payload.type === "envi") {
    const out: Photo[] = [];
    const pres = pick(dl, "presentation_web", "presentation", "infographic");
    if (pres)
      out.push({ id: "presentation", label: "Presentation", src: href(pres)!, alt: pres.alt ?? "ENVI presentation",
        pkg: href(pick(dl, "presentation")), print: href(pick(dl, "presentation_pdf")) });
    const poster = pick(dl, "poster_web", "poster");
    if (poster)
      out.push({ id: "poster", label: "A4 poster", src: href(poster)!, alt: "ENVI A4 poster with the full recommendations",
        pkg: href(pick(dl, "poster")), print: href(pick(dl, "poster_pdf")) });
    const map = pick(dl.filter((d) => d.layer === "envi"), "jpg", "png");
    if (!out.length && map) out.push({ id: "map", label: "Map", src: href(map)!, alt: map.alt ?? "ENVI map" });
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
  const photos = useMemo(() => photosOf(payload), [payload]);
  const byLayer = photos.some((p) => p.layer);
  const [own, setOwn] = useState(0); // index for photos that are not tied to a map layer (ENVI)
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
      if (e.key === "Escape") onClose();
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
  }, [select, idx, onClose]);

  useEffect(() => {
    for (const d of [-1, 1]) {
      const p = photos[(idx + d + photos.length) % photos.length];
      if (p) new Image().src = p.src;
    }
  }, [idx, photos]);

  const t = payload.texts;
  const recs = (t.recommendations ?? "").split("\n").filter((l) => l.trim());

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
        <button className="photo-close" onClick={onClose} aria-label="Close photo mode (Esc)">
          ✕ Close
        </button>
      </header>

      <div className="photo-body">
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

        <aside className="photo-side">
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
