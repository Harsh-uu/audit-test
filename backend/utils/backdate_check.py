"""Detect a mismatch between a meeting's user-entered `date` and the real
wall-clock time recording actually happened.

`meetings.date` is a free-text-validated field (see CreateMeetingRequest in
routers/meetings.py) with no bound against `now()` — it's deliberately left
open so a manager can log a supervision that took place earlier and is only
being entered/recorded now. Nothing here blocks that. This module only
*detects* a large mismatch so it can be surfaced transparently (Audit Trail +
report header) instead of silently hidden, per the resolved bug report.

Threshold rationale: meetings.date is stored as a naive TIMESTAMP with no
timezone (see migrations/m019_meetings_date_timestamp.py — deliberately not
TIMESTAMPTZ, to avoid misinterpreting a local scheduling time as UTC), while
recording timestamps are real UTC times. A 48h threshold comfortably absorbs
that timezone-naive slop (max real-world offset is ~14h) and any normal
prep-to-recording delay, while still catching genuine backdating/postdating
(e.g. a date many months away from the actual recording).
"""
from datetime import datetime
from typing import Optional

BACKDATE_THRESHOLD_HOURS = 48


def detect_backdate_mismatch(declared_date: Optional[str], actual_ts: Optional[str]) -> Optional[str]:
    """Return a human-readable note if `declared_date` (meetings.date) is more
    than BACKDATE_THRESHOLD_HOURS away from `actual_ts` (a real recording
    timestamp), else None. Never raises — any parse failure is treated as
    "no mismatch detected" so this is purely additive and can't break the
    caller's main flow.
    """
    if not declared_date or not actual_ts:
        return None
    try:
        declared = datetime.fromisoformat(str(declared_date)).replace(tzinfo=None)
        actual = datetime.fromisoformat(str(actual_ts).replace("Z", "+00:00")).replace(tzinfo=None)
        delta_hours = abs((actual - declared).total_seconds()) / 3600
        if delta_hours <= BACKDATE_THRESHOLD_HOURS:
            return None
        when = "before" if declared < actual else "after"
        return (
            f"Meeting was dated {declared.strftime('%d/%m/%Y %H:%M')}, "
            f"{when} the actual recording start ({actual.strftime('%d/%m/%Y %H:%M')})."
        )
    except (ValueError, TypeError):
        return None
