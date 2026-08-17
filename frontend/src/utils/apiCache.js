/**
 * Lightweight stale-while-revalidate cache for stable GET endpoints.
 * Avoids redundant DB round-trips when the same data is fetched on navigation.
 */
import axios from "axios";

const _cache = new Map();

// TTL in milliseconds per URL pattern (path substring match).
// IMPORTANT: more-specific patterns MUST appear before any shorter prefix that
// would otherwise match first (e.g. /schedules/meeting-types before /schedules/).
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
  "/schedules/meeting-types":   300_000,   // 5 min  — must be before /schedules/
  "/schedules/due":              30_000,   // 30 s   — due-date calculations; must be before /schedules/
  "/schedules/":                 30_000,   // 30 s   — full schedule list
  "/prep/focus-topics":         300_000,   // 5 min
};

// Minimum item count for array responses before the result is considered
// valid enough to cache. If a response returns fewer items than this threshold
// (e.g. during a server restart) it is NOT cached — the next request retries live.
const MIN_ITEMS_MAP = {
  "/admin/standards": 10,   // should always have CQC + Care Cert (47 + 16 minimum)
};

function _ttl(url) {
  const path = url.replace(/^https?:\/\/[^/]+/, "");
  for (const [pattern, ttl] of Object.entries(TTL_MAP)) {
    if (path.includes(pattern)) return ttl;
  }
  return 0;
}

function _minItems(url) {
  const path = url.replace(/^https?:\/\/[^/]+/, "");
  for (const [pattern, min] of Object.entries(MIN_ITEMS_MAP)) {
    if (path.includes(pattern)) return min;
  }
  return 0;
}

/**
 * Drop-in replacement for axios.get that caches stable responses.
 * Falls back to a live request when no TTL is configured for the URL.
 * Never caches a response whose array length falls below MIN_ITEMS_MAP threshold
 * (guards against caching transient empty responses during server restarts).
 */
export async function cachedGet(url, config = {}) {
  const ttl = _ttl(url);
  if (ttl) {
    const hit = _cache.get(url);
    if (hit && Date.now() - hit.ts < ttl) return hit.res;
  }
  const res = await axios.get(url, config);
  if (ttl) {
    const min = _minItems(url);
    const count = Array.isArray(res.data) ? res.data.length : null;
    if (min > 0 && count !== null && count < min) {
      // Transient empty/short response — skip cache so next call retries live
      console.warn(`[cache] Skipping cache for ${url}: got ${count} items, expected ≥${min}`);
    } else {
      _cache.set(url, { res, ts: Date.now() });
    }
  }
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
