/**
 * Lightweight stale-while-revalidate cache for stable GET endpoints.
 * Avoids redundant DB round-trips when the same data is fetched on navigation.
 */
import axios from "axios";

const _cache = new Map();

// TTL in milliseconds per URL pattern (path substring match)
const TTL_MAP = {
  "/auth/me":                    60_000,   // 1 min
  "/org/branding":              300_000,   // 5 min
  "/org/structure":              60_000,   // 1 min
  "/admin/users":                30_000,   // 30 s
  "/admin/people-stats":         30_000,   // 30 s
  "/admin/meetings-brief":       30_000,   // 30 s
  "/admin/team-insights":        60_000,   // 1 min  (covers /team-insights/registers etc.)
  "/admin/standards/documents": 120_000,   // 2 min
  "/admin/standards":           600_000,   // 10 min (CQC/Care Cert standards never change)
  "/admin/template":            300_000,   // 5 min
  "/schedules/meeting-types":   300_000,   // 5 min
  "/prep/focus-topics":         300_000,   // 5 min
};

function _ttl(url) {
  const path = url.replace(/^https?:\/\/[^/]+/, "");
  for (const [pattern, ttl] of Object.entries(TTL_MAP)) {
    if (path.includes(pattern)) return ttl;
  }
  return 0;
}

/**
 * Drop-in replacement for axios.get that caches stable responses.
 * Falls back to a live request when no TTL is configured for the URL.
 */
export async function cachedGet(url, config = {}) {
  const ttl = _ttl(url);
  if (ttl) {
    const hit = _cache.get(url);
    if (hit && Date.now() - hit.ts < ttl) return hit.res;
  }
  const res = await axios.get(url, config);
  if (ttl) _cache.set(url, { res, ts: Date.now() });
  return res;
}

/**
 * Bust cached entries whose URL contains any of the given patterns.
 * Call this after mutations (PUT/POST/DELETE) on cacheable resources.
 * e.g. invalidateCache("/admin/users") after editing a user.
 */
export function invalidateCache(...patterns) {
  for (const key of _cache.keys()) {
    if (patterns.some(p => key.includes(p))) _cache.delete(key);
  }
}
