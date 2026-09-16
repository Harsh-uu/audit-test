"""Need Reviewer — detects recurring commissioning/care-review signals about a
named service user across supervision meetings (England/Wales/Scotland/NI only).

Not scoped to Ofsted — "commissioning"/care-review concepts don't apply there.
"""
import logging

logger = logging.getLogger(__name__)

CONCERN_CATEGORIES = {
    "insufficient_visit_time",
    "missed_or_late_medication",
    "repeated_falls",
    "missed_or_incomplete_visits",
    "deteriorating_condition_unaddressed",
    "family_requesting_more_support",
    "staffing_capacity_mismatch",
}

_CATEGORY_LABELS = {
    "insufficient_visit_time": "insufficient visit time",
    "missed_or_late_medication": "missed or late medication",
    "repeated_falls": "repeated falls",
    "missed_or_incomplete_visits": "missed or incomplete visits",
    "deteriorating_condition_unaddressed": "a deteriorating condition not being addressed",
    "family_requesting_more_support": "family/carer requesting more support",
    "staffing_capacity_mismatch": "a staffing/capacity mismatch",
}

THRESHOLD = 3


async def process_need_review_signals(conn, org_id: str, meeting_id: str, analysis_result: dict, jurisdiction: str) -> None:
    """Stores this meeting's need_review_signals and, on the 3rd+ matching hit
    org-wide, appends a Need Reviewer entry to analysis_result['risks'] in place.
    No-op for Ofsted orgs. Exact (case-insensitive) name matching only."""
    if jurisdiction and jurisdiction.startswith("ofsted"):
        return
    raw_signals = analysis_result.get("need_review_signals") or []
    if not raw_signals:
        return

    # Dedupe within this single meeting — at most one row per person+category
    seen = set()
    clean_signals = []
    for s in raw_signals:
        if not isinstance(s, dict):
            continue
        person_name = str(s.get("person_name") or "").strip()
        concern_category = str(s.get("concern_category") or "").strip()
        quote = str(s.get("quote") or "").strip()
        if not person_name or concern_category not in CONCERN_CATEGORIES:
            continue
        key = (person_name.lower(), concern_category)
        if key in seen:
            continue
        seen.add(key)
        clean_signals.append({"person_name": person_name, "concern_category": concern_category, "quote": quote})

    if not clean_signals:
        return

    new_risks = []
    for sig in clean_signals:
        try:
            await conn.execute(
                "INSERT INTO need_review_signals (org_id, meeting_id, person_name, concern_category, quote) VALUES ($1,$2,$3,$4,$5)",
                org_id, meeting_id, sig["person_name"], sig["concern_category"], sig["quote"],
            )
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM need_review_signals WHERE org_id=$1 AND LOWER(person_name)=LOWER($2) AND concern_category=$3",
                org_id, sig["person_name"], sig["concern_category"],
            )
        except Exception as e:
            logger.warning(f"Need Reviewer signal insert failed for meeting {meeting_id}: {e}")
            continue

        if count >= THRESHOLD:
            label = _CATEGORY_LABELS.get(sig["concern_category"], sig["concern_category"])
            new_risks.append({
                "id": f"needreview_{sig['person_name'].lower().replace(' ', '_')}_{sig['concern_category']}",
                "text": f"Need Reviewer — {label} raised {count} times for {sig['person_name']} across recent supervisions",
                "severity": "high",
                "transcript_excerpt": sig["quote"],
                "suggested_resolutions": [
                    f"Consider a care review or reassessment referral for {sig['person_name']}",
                    "Discuss with the manager whether the current care package still meets this person's needs",
                ],
            })

    if new_risks:
        analysis_result["risks"] = list(analysis_result.get("risks") or []) + new_risks
