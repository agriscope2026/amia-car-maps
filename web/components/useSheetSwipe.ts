"use client";

import { useEffect, type RefObject } from "react";

const PEEK = 52; // height of the sheet handle left showing when the sheet is closed (matches globals.css)
const MOBILE = "(max-width: 820px)";

/**
 * Phone bottom sheet: drag the handle up/down to open/close it (the sheet follows the finger), or pull the
 * content down when it is scrolled to the top to close it. A short flick is enough.
 */
export function useSheetSwipe(ref: RefObject<HTMLElement | null>, open: boolean, setOpen: (open: boolean) => void) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const mq = window.matchMedia(MOBILE);
    let start: { y: number; t: number; h: number; handle: boolean } | null = null;
    let dy = 0;
    let dragging = false;
    let swallowClick = false;

    const onStart = (e: TouchEvent) => {
      if (!mq.matches || e.touches.length !== 1) return;
      const handle = !!(e.target as Element).closest(".sheet-handle");
      // from the content only when it can't scroll further up, so normal scrolling still works
      if (!handle && !(open && el.scrollTop <= 0)) return;
      start = { y: e.touches[0].clientY, t: Date.now(), h: el.offsetHeight, handle };
      dy = 0;
      dragging = false;
    };
    const onMove = (e: TouchEvent) => {
      if (!start) return;
      dy = e.touches[0].clientY - start.y;
      if (!dragging) {
        if (Math.abs(dy) < 8) return;
        if (!start.handle && dy < 0) {
          start = null; // pushing the content up: let it scroll
          return;
        }
        dragging = true;
        el.style.transition = "none";
      }
      e.preventDefault();
      const closed = start.h - PEEK;
      const y = Math.min(closed, Math.max(0, (open ? 0 : closed) + dy));
      el.style.transform = `translateY(${y}px)`;
    };
    const onEnd = () => {
      if (!start) return;
      const flick = Math.abs(dy) / Math.max(1, Date.now() - start.t) > 0.4;
      el.style.transition = "";
      el.style.transform = "";
      if (dragging) {
        swallowClick = start.handle; // the handle's own tap-to-toggle must not undo the swipe
        if (dy < 0 && (dy < -40 || flick)) setOpen(true);
        else if (dy > 0 && (dy > 40 || flick)) setOpen(false);
      }
      start = null;
      dragging = false;
    };
    const onClick = (e: MouseEvent) => {
      if (!swallowClick) return;
      swallowClick = false;
      e.preventDefault();
      e.stopPropagation();
    };

    el.addEventListener("touchstart", onStart, { passive: true });
    el.addEventListener("touchmove", onMove, { passive: false });
    el.addEventListener("touchend", onEnd);
    el.addEventListener("touchcancel", onEnd);
    el.addEventListener("click", onClick, true);
    return () => {
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend", onEnd);
      el.removeEventListener("touchcancel", onEnd);
      el.removeEventListener("click", onClick, true);
    };
  }, [ref, open, setOpen]);
}
