"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const MIN = 1;
const MAX = 8;

/**
 * Zoomable, pannable image: wheel / pinch / double-click to zoom (around the pointer), drag to pan,
 * buttons for − + Fit and 100 %, keyboard + − 0. The image starts fitted to its box.
 */
export default function ZoomImage({ src, alt }: { src: string; alt: string }) {
  const box = useRef<HTMLDivElement>(null);
  const img = useRef<HTMLImageElement>(null);
  const [z, setZ] = useState({ s: 1, x: 0, y: 0 });
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ d: number; s: number } | null>(null);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  useEffect(() => setZ({ s: 1, x: 0, y: 0 }), [src]);

  /** keep the zoomed image covering the box (or centred when it is smaller than the box) */
  const clamp = useCallback((s: number, x: number, y: number) => {
    const b = box.current?.getBoundingClientRect();
    const i = img.current;
    if (!b || !i || s === 1) return { s, x: 0, y: 0 };
    const fit = (boxSize: number, offset: number, size: number, v: number) =>
      size <= boxSize ? (boxSize - size) / 2 - offset : Math.max(boxSize - offset - size, Math.min(-offset, v));
    return {
      s,
      x: fit(b.width, i.offsetLeft, i.offsetWidth * s, x),
      y: fit(b.height, i.offsetTop, i.offsetHeight * s, y),
    };
  }, []);

  /** zoom to scale `s2` keeping the point (px, py) – relative to the image's untransformed origin – fixed */
  const zoomAt = useCallback(
    (s2: number, px?: number, py?: number) => {
      setZ((cur) => {
        const s = Math.max(MIN, Math.min(MAX, s2));
        const i = img.current;
        const ox = px ?? (i ? i.offsetWidth / 2 : 0);
        const oy = py ?? (i ? i.offsetHeight / 2 : 0);
        // point under the cursor in image space stays put: p = t + q*s  →  t2 = p - (p - t) * s2/s
        const x = ox - (ox - cur.x) * (s / cur.s);
        const y = oy - (oy - cur.y) * (s / cur.s);
        return s === 1 ? { s: 1, x: 0, y: 0 } : clamp(s, x, y);
      });
    },
    [clamp],
  );

  const local = (e: { clientX: number; clientY: number }) => {
    const r = img.current!.parentElement!.getBoundingClientRect();
    const i = img.current!;
    return { x: e.clientX - r.left - i.offsetLeft, y: e.clientY - r.top - i.offsetTop };
  };

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const p = local(e);
      zoomAt(z.s * (e.deltaY < 0 ? 1.2 : 1 / 1.2), p.x, p.y);
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [z.s, zoomAt]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "+" || e.key === "=") zoomAt(z.s * 1.4);
      else if (e.key === "-" || e.key === "_") zoomAt(z.s / 1.4);
      else if (e.key === "0") setZ({ s: 1, x: 0, y: 0 });
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [z.s, zoomAt]);

  const onDown = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture?.(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      pinch.current = { d: Math.hypot(a.x - b.x, a.y - b.y), s: z.s };
      drag.current = null;
    } else if (z.s > 1) {
      drag.current = { x: e.clientX, y: e.clientY, ox: z.x, oy: z.y };
    }
  };
  const onMove = (e: React.PointerEvent) => {
    if (!pointers.current.has(e.pointerId)) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch.current && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      const mid = local({ clientX: (a.x + b.x) / 2, clientY: (a.y + b.y) / 2 });
      zoomAt(pinch.current.s * (d / pinch.current.d), mid.x, mid.y);
    } else if (drag.current) {
      // read the drag start now: the state updater runs later, possibly after pointer-up has cleared drag.current
      const d = drag.current;
      const x = d.ox + e.clientX - d.x, y = d.oy + e.clientY - d.y;
      setZ((cur) => clamp(cur.s, x, y));
    }
  };
  const onUp = (e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
    drag.current = null;
  };
  const onDouble = (e: React.MouseEvent) => {
    const p = local(e);
    if (z.s > 1.05) setZ({ s: 1, x: 0, y: 0 });
    else zoomAt(2.5, p.x, p.y);
  };
  const actual = () => {
    const i = img.current;
    if (i && i.naturalWidth) zoomAt(Math.max(1, i.naturalWidth / i.offsetWidth));
  };

  const pct = img.current?.naturalWidth ? Math.round(((img.current.offsetWidth * z.s) / img.current.naturalWidth) * 100) : null;

  return (
    <div className="zoom">
      <div
        className={`zoom-box ${z.s > 1 ? "zoomed" : ""}`}
        ref={box}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onUp}
        onDoubleClick={onDouble}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          ref={img}
          src={src}
          alt={alt}
          draggable={false}
          style={{ transform: `translate(${z.x}px, ${z.y}px) scale(${z.s})` }}
        />
      </div>
      <div className="zoom-tools" role="toolbar" aria-label="Zoom">
        <button onClick={() => zoomAt(z.s / 1.4)} disabled={z.s <= MIN} aria-label="Zoom out (−)">−</button>
        <span className="zoom-pct" aria-live="polite">{pct ? `${pct}%` : ""}</span>
        <button onClick={() => zoomAt(z.s * 1.4)} disabled={z.s >= MAX} aria-label="Zoom in (+)">+</button>
        <button onClick={() => setZ({ s: 1, x: 0, y: 0 })} disabled={z.s === 1} aria-label="Fit to screen (0)">Fit</button>
        <button onClick={actual} aria-label="Actual pixels">100%</button>
      </div>
    </div>
  );
}
