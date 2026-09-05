"""
In-process cache for standards and org context.

Standards data is seeded once and never changes — loaded at startup and
held in memory for the process lifetime with zero DB reads thereafter.

Org jurisdiction/service_type almost never changes — cached per org_id with a
5-minute TTL, invalidated explicitly when an admin updates org settings. The TTL
is a backstop for multi-instance deployments: invalidate_org() only clears the
process that handled the admin's request, so other replicas behind a load
balancer would otherwise keep serving the old jurisdiction forever (same
pattern used by _custom_docs/_meeting_types_cache below).

Custom standards documents change only when an admin uploads/toggles one —
cached per org_id, invalidated on any write to standards_documents.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# ── System standards ─────────────────────────────────────────────────────────
# Keyed by a stable string that encodes the query pattern.
# Populated once at startup via warm(). Never expire.
_system: dict[str, list[dict]] = {}
_warmed = False


async def warm(conn) -> None:
    """Load all system standards into memory. Call once at startup."""
    global _warmed
    if _warmed:
        return
    rows = await conn.fetch(
        "SELECT type, jurisdiction, reference, name, description, key_questions, sub_outcomes "
        "FROM standards_entries WHERE is_system = TRUE AND is_active = TRUE "
        "ORDER BY type, reference"
    )
    for r in rows:
        d = dict(r)
        t = d.get("type", "")
        j = d.get("jurisdiction") or ""
        _system.setdefault(t, []).append(d)
        if j:
            _system.setdefault(f"{t}:{j}", []).append(d)
    _warmed = True
    by_type = {}
    for r in rows:
        by_type.setdefault(r["type"], 0)
        by_type[r["type"]] += 1
    logger.info("Standards cache warmed: %d entries — %s", len(rows), dict(by_type))


async def rewarm(conn) -> None:
    """Force a full cache reload from the DB.
    Call after inserting new system standards rows within the same process run
    (e.g. seed_standards inserts CQC on a deployment that previously only had Care Cert).
    """
    global _warmed
    _warmed = False
    _system.clear()
    await warm(conn)
    logger.info("Standards cache re-warmed")


def get_system(type_: str, jurisdiction: str | None = None) -> list[dict]:
    """Return cached system standards. Falls back to [] if not warmed yet."""
    key = f"{type_}:{jurisdiction}" if jurisdiction else type_
    return list(_system.get(key, []))


# ── Org jurisdiction / service_type ──────────────────────────────────────────
# {org_id: (fetched_at_ts, {"jurisdiction": str, "service_type": str})}
_org_info: dict[str, tuple[float, dict]] = {}
_ORG_INFO_TTL = 300  # 5 minutes — backstop in case invalidate_org() is missed
                     # (e.g. a different replica handled the admin's update)


def get_org_info(org_id: str) -> dict | None:
    entry = _org_info.get(org_id)
    if entry is None:
        return None
    fetched_at, info = entry
    if time.monotonic() - fetched_at > _ORG_INFO_TTL:
        _org_info.pop(org_id, None)
        return None
    return info


def set_org_info(org_id: str, jurisdiction: str, service_type: str) -> None:
    _org_info[org_id] = (time.monotonic(), {"jurisdiction": jurisdiction or "england",
                                             "service_type": service_type or ""})


def invalidate_org(org_id: str) -> None:
    """Call whenever org settings or custom standards change for this org."""
    _org_info.pop(org_id, None)
    _custom_docs.pop(org_id, None)
    logger.debug("Standards cache invalidated for org=%s", org_id)


# ── Custom standards documents ────────────────────────────────────────────────
# {org_id: (fetched_at_ts, list[dict])}
_custom_docs: dict[str, tuple[float, list[dict]]] = {}
_CUSTOM_TTL = 300  # 5 minutes — backstop in case invalidation is missed


def get_custom_docs(org_id: str) -> list[dict] | None:
    entry = _custom_docs.get(org_id)
    if entry is None:
        return None
    fetched_at, docs = entry
    if time.monotonic() - fetched_at > _CUSTOM_TTL:
        _custom_docs.pop(org_id, None)
        return None
    return list(docs)


def set_custom_docs(org_id: str, docs: list[dict]) -> None:
    _custom_docs[org_id] = (time.monotonic(), docs)
