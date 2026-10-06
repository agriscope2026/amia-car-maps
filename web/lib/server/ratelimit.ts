import "server-only";
import { HttpError } from "./auth";

// Simple fixed-window limiter (per server instance). For multi-instance deployments use the
// rate_limits table or an edge KV store.
const hits = new Map<string, { start: number; n: number }>();

export function rateLimit(key: string, max: number, windowMs: number) {
  const now = Date.now();
  const h = hits.get(key);
  if (!h || now - h.start > windowMs) {
    hits.set(key, { start: now, n: 1 });
    return;
  }
  h.n++;
  if (h.n > max) throw new HttpError(429, "Too many attempts. Please wait a few minutes and try again.");
}
