"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

/** Set in localStorage once a visitor has finished or skipped the guide. Bump the suffix to show it again after big UI changes. */
export const GUIDE_SEEN_KEY = "amia-guide-seen-v1";

export function guideSeen(): boolean {
  try {
    return localStorage.getItem(GUIDE_SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

function markSeen() {
  try {
    localStorage.setItem(GUIDE_SEEN_KEY, "1");
  } catch {
    /* private window – the guide will simply show again next visit */
  }
}

export interface GuideStep {
  /** `[data-tour="…"]` target; omitted for a centred message. */
  target?: string;
  title: string;
  body: React.ReactNode;
  /** On phones the controls live in a bottom sheet. It opens when the target is inside it; for steps without a
   *  target on the page yet, this says whether to open it (true) or close it so the map shows (false). */
  panel?: boolean;
  /** Show an animated "tap here" pointer in the middle of the target. */
  tap?: boolean;
  /** Target is inside the municipality card, which the dashboard opens for an example municipality during this step. */
  demo?: boolean;
}

export const GUIDE_STEPS: GuideStep[] = [
  {
    title: "Welcome to AMIA CAR MAPS",
    body: (
      <>
        <p>These maps show rainfall, drought and El Niño risk for every municipality in the Cordillera, with farm advice from DA-RFO-CAR.</p>
        <p>This short guide shows you how to use them. It takes about a minute.</p>
      </>
    ),
    panel: false,
  },
  {
    target: "maptype",
    title: "1. Choose a map type",
    body: (
      <>
        <p>Tap a button to switch maps:</p>
        <ul>
          <li><strong>ENVI</strong>: El Niño vulnerability per municipality</li>
          <li><strong>10-day rainfall</strong>: rain expected in the coming days</li>
          <li><strong>Seasonal rainfall</strong>: rain outlook for the coming months</li>
          <li><strong>Drought forecast</strong>: where dry conditions are expected</li>
        </ul>
        <p className="tour-muted">Greyed-out buttons have no published map yet.</p>
      </>
    ),
    panel: true,
  },
  {
    target: "period",
    title: "2. Pick the date",
    body: (
      <>
        <p>The newest issue is shown first. Open this list to see older issues.</p>
        <p>If a map covers several days or months, choose one below it, or press <strong>▶</strong> to play through them.</p>
      </>
    ),
    panel: true,
  },
  {
    target: "map",
    title: "3. Tap a municipality",
    body: (
      <>
        <p>Each shape on the map is a municipality. <strong>Click or tap a shape</strong> to open a card with its details.</p>
        <p>Press <strong>Next</strong> to see an example.</p>
        <p className="tour-muted">Drag to move the map, and pinch or scroll to zoom.</p>
      </>
    ),
    panel: false,
    tap: true,
  },
  {
    target: "area-value",
    title: "4. The municipality card",
    body: (
      <>
        <p>This card opened for the municipality you tapped. Its name and province are at the top, followed by its value on the map and what that level means.</p>
        <p>Scroll down the card for more: day-by-day or month-by-month values, indicators, standing crops and farm advice.</p>
        <p className="tour-muted">Close it with <strong>✕</strong>, by tapping outside it, or with Esc.</p>
      </>
    ),
    panel: false,
    demo: true,
  },
  {
    target: "area-recs",
    title: "5. Recommendations for that place",
    body: (
      <>
        <p>Lower in the card are the recommendations. Advice that names this <strong>municipality or its province</strong> is shown first, in yellow.</p>
        <p>Open <strong>All recommendations</strong> to read the full list for the region.</p>
      </>
    ),
    panel: false,
    demo: true,
  },
  {
    target: "recs",
    title: "6. Regional recommendations",
    body: <p>The same advice for the whole region is also listed here, at the bottom of the panel.</p>,
    panel: true,
  },
  {
    target: "photo",
    title: "7. View as photo",
    body: (
      <>
        <p><strong>Photo mode</strong> shows the finished, official map images with the recommendations printed on them.</p>
        <p>Use <strong>‹ ›</strong> to flip through them. Each image has its own download button.</p>
      </>
    ),
    panel: false,
  },
  {
    target: "downloads",
    title: "8. Download the maps",
    body: (
      <>
        <p>Tap <strong>⤓ PNG</strong> for an image or <strong>⤓ PDF</strong> to print. The map you are viewing is highlighted.</p>
        <p>The button at the bottom downloads every map in one ZIP file.</p>
      </>
    ),
    panel: true,
  },
  {
    target: "help",
    title: "You're all set",
    body: <p>Tap <strong>How to use</strong> at any time to see this guide again. To send someone the exact map you are viewing, use <strong>Copy share link</strong> in the panel.</p>,
    panel: false,
  },
];

type Rect = { top: number; left: number; width: number; height: number };
type Side = "bottom" | "top" | "left" | "right" | "center";

const PAD = 6; // spotlight padding around the target
const GAP = 14; // distance between spotlight and card
const EDGE = 12; // min distance from the viewport edges

/** First matching target that is displayed (a control can exist twice, e.g. the map-type chips on phones and buttons in the panel). */
const find = (t?: string) =>
  t ? [...document.querySelectorAll<HTMLElement>(`[data-tour="${t}"]`)].find((e) => e.getClientRects().length > 0) ?? null : null;

/** Visible part of an element, clipped to its scroll container and the viewport (so a tall panel item doesn't spill). */
function visibleRect(el: HTMLElement): Rect {
  let r = el.getBoundingClientRect();
  let top = r.top, left = r.left, bottom = r.bottom, right = r.right;
  for (let p = el.parentElement; p; p = p.parentElement) {
    const s = getComputedStyle(p);
    if (/(auto|scroll|hidden)/.test(s.overflowY)) {
      r = p.getBoundingClientRect();
      top = Math.max(top, r.top);
      bottom = Math.min(bottom, r.bottom);
      left = Math.max(left, r.left);
      right = Math.min(right, r.right);
    }
  }
  top = Math.max(top, 0);
  left = Math.max(left, 0);
  bottom = Math.min(bottom, window.innerHeight);
  right = Math.min(right, window.innerWidth);
  return { top, left, width: Math.max(0, right - left), height: Math.max(0, bottom - top) };
}

export default function GuideTour({ onStep, onClose, demoTargets }: {
  /** `inPanel`: the target sits in the controls panel (the phone bottom sheet must be open to see it). */
  onStep: (s: GuideStep, inPanel: boolean) => void;
  onClose: () => void;
  /** Targets inside the example municipality card that will exist once it opens. */
  demoTargets: string[];
}) {
  // only steps whose target is on the page (e.g. no Photo mode or Downloads for some maps)
  const steps = useMemo(
    () => GUIDE_STEPS.filter((s) => !s.target || (s.demo ? demoTargets.includes(s.target) : find(s.target))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const [i, setI] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);
  const [card, setCard] = useState({ w: 340, h: 260 });
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const step = steps[i];
  const last = i === steps.length - 1;

  const finish = useCallback(() => {
    markSeen();
    onClose();
  }, [onClose]);

  const measure = useCallback(() => {
    const el = find(step?.target);
    const next = el ? visibleRect(el) : null;
    setRect((prev) =>
      prev && next && (["top", "left", "width", "height"] as const).every((k) => Math.abs(prev[k] - next[k]) < 1) ? prev : next,
    );
  }, [step?.target]);

  // move to the step: open/close the mobile sheet, scroll the target into view, then measure (after the sheet animates)
  useEffect(() => {
    if (!step) return;
    const el = find(step.target);
    onStep(step, el ? !!el.closest(".panel") : !!step.panel);
    const t1 = setTimeout(() => {
      // demo targets only exist once the card has rendered, so look them up again
      (find(step.target) ?? el)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      measure();
      nextRef.current?.focus(); // the municipality card grabs focus when it opens
    }, 60);
    const t2 = setTimeout(measure, 380);
    nextRef.current?.focus();
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [step, onStep, measure]);

  useEffect(() => {
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [measure]);

  // card size feeds its placement; measure only when the size really changes (measuring after every render
  // could loop forever when placement and size kept nudging each other)
  useLayoutEffect(() => {
    const c = cardRef.current;
    if (!c) return;
    const update = () =>
      setCard((prev) => {
        const w = c.offsetWidth, h = c.offsetHeight;
        return Math.abs(prev.w - w) < 2 && Math.abs(prev.h - h) < 2 ? prev : { w, h };
      });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(c);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") finish();
      else if (e.key === "ArrowRight") setI((n) => Math.min(n + 1, steps.length - 1));
      else if (e.key === "ArrowLeft") setI((n) => Math.max(n - 1, 0));
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [finish, steps.length]);

  if (!step) return null;

  // spotlight box and card placement: below, above, left, right of the target – first that fits, else centred
  const vw = typeof window !== "undefined" ? window.innerWidth : 1024;
  const vh = typeof window !== "undefined" ? window.innerHeight : 768;
  const hole = rect && rect.width > 0 && rect.height > 0
    ? { top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 }
    : null;
  let side: Side = "center";
  let pos = { top: (vh - card.h) / 2, left: (vw - card.w) / 2 };
  if (hole) {
    const cx = hole.left + hole.width / 2, cy = hole.top + hole.height / 2;
    const clampX = (x: number) => Math.min(Math.max(x, EDGE), vw - card.w - EDGE);
    const clampY = (y: number) => Math.min(Math.max(y, EDGE), vh - card.h - EDGE);
    const fits: [Side, boolean, { top: number; left: number }][] = [
      ["bottom", hole.top + hole.height + GAP + card.h + EDGE <= vh, { top: hole.top + hole.height + GAP, left: clampX(cx - card.w / 2) }],
      ["top", hole.top - GAP - card.h >= EDGE, { top: hole.top - GAP - card.h, left: clampX(cx - card.w / 2) }],
      ["left", hole.left - GAP - card.w >= EDGE, { top: clampY(cy - card.h / 2), left: hole.left - GAP - card.w }],
      ["right", hole.left + hole.width + GAP + card.w + EDGE <= vw, { top: clampY(cy - card.h / 2), left: hole.left + hole.width + GAP }],
    ];
    const hit = fits.find(([, ok]) => ok);
    if (hit) [side, , pos] = hit;
    else pos = { top: vh - card.h - EDGE, left: (vw - card.w) / 2 }; // target fills the screen (the map on phones): dock at the bottom
  }
  // arrow points from the card at the target's centre
  const arrow = hole && side !== "center"
    ? side === "bottom" || side === "top"
      ? { left: Math.min(Math.max(hole.left + hole.width / 2 - pos.left, 18), card.w - 18) }
      : { top: Math.min(Math.max(hole.top + hole.height / 2 - pos.top, 18), card.h - 18) }
    : null;

  return (
    <div className="tour" aria-live="polite">
      <div className="tour-block" onClick={(e) => e.stopPropagation()} />
      {hole ? <div className="tour-hole" style={hole} /> : <div className="tour-dim" />}
      {hole && step.tap && (
        <div className="tour-tap" style={{ top: hole.top + hole.height * 0.42, left: hole.left + hole.width / 2 }} aria-hidden>
          <span className="tour-ripple" />
          <span className="tour-hand">👆</span>
        </div>
      )}
      <div
        ref={cardRef}
        className={`tour-card side-${side}`}
        style={pos}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-body"
      >
        {arrow && <span className="tour-arrow" style={arrow} aria-hidden />}
        <div className="tour-count">
          Step {i + 1} of {steps.length}
          <span className="tour-dots" aria-hidden>
            {steps.map((_, n) => <span key={n} className={n === i ? "on" : ""} />)}
          </span>
        </div>
        <h2 id="tour-title">{step.title}</h2>
        <div id="tour-body" className="tour-body">{step.body}</div>
        <div className="tour-actions">
          {!last && <button className="tour-skip" onClick={finish}>Skip guide</button>}
          <span className="tour-spacer" />
          {i > 0 && <button className="secondary" onClick={() => setI(i - 1)}>Back</button>}
          <button ref={nextRef} onClick={() => (last ? finish() : setI(i + 1))}>{last ? "Start exploring" : i === 0 ? "Show me" : "Next"}</button>
        </div>
      </div>
    </div>
  );
}
