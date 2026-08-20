"""iteration_88 — validation-fix tests for POST /api/review/{meeting_id}/evidence/bulk-action

Verifies the Pydantic Literal constraints added in routers/review.py:
  confidence: Literal["likely_evidence","possible_evidence"]  -> 422 otherwise
  status:     Literal["accepted","rejected","needs_followup"] = "accepted" -> 422 otherwise

Run serially:  cd /app/backend && python3 -m pytest tests/test_iter88_fixes.py -q -n 0
"""
import asyncio
import os

import pytest
import requests
from dotenv import dotenv_values

from test_iter87_bulk_accept import login, MEETING_ID, BASE, _seed, _set_meeting_status  # noqa


def seed_mix(mid, mode="mix", status=None):
    return asyncio.run(_seed(mid, mode, status=status))


def set_status(mid, status):
    return asyncio.run(_set_meeting_status(mid, status))


@pytest.fixture(scope="module")
def admin():
    return login("admin@supervision.com", "Admin123!")


@pytest.fixture(autouse=True)
def seeded():
    seed_mix(MEETING_ID, "mix", status="in_review")
    yield
    set_status(MEETING_ID, "in_review")


class TestBulkActionValidation:
    """LOW FIX #2 — Literal validation on confidence/status"""

    @pytest.mark.parametrize("bad", ["foo", "", "needs_review", "not_enough_evidence", "LIKELY_EVIDENCE", None, 123])
    def test_bad_confidence_returns_422(self, admin, bad):
        r = admin.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action",
                       json={"confidence": bad, "status": "accepted"}, timeout=60)
        assert r.status_code == 422, f"confidence={bad!r} -> {r.status_code}: {r.text[:300]}"

    @pytest.mark.parametrize("bad", ["bar", "pending", "ACCEPTED", "", 1])
    def test_bad_status_returns_422(self, admin, bad):
        r = admin.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action",
                       json={"confidence": "likely_evidence", "status": bad}, timeout=60)
        assert r.status_code == 422, f"status={bad!r} -> {r.status_code}: {r.text[:300]}"

    @pytest.mark.parametrize("good", ["accepted", "rejected", "needs_followup"])
    def test_valid_statuses_accepted(self, admin, good):
        r = admin.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action",
                       json={"confidence": "likely_evidence", "status": good}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["updated_count"] >= 1, body
        # verify persistence
        after = admin.get(f"{BASE}/review/{MEETING_ID}", timeout=60).json()["analysis"]
        found = [i for f in ("cqc_mappings", "care_cert_mappings", "custom_mappings")
                 for i in (after.get(f) or []) if i.get("confidence") == "likely_evidence"
                 and i.get("status") == good]
        assert len(found) >= 1, f"no likely item persisted with status={good}"

    def test_status_defaults_to_accepted(self, admin):
        r = admin.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action",
                       json={"confidence": "possible_evidence"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["updated_count"] >= 1
        after = admin.get(f"{BASE}/review/{MEETING_ID}", timeout=60).json()["analysis"]
        pend = [i for f in ("cqc_mappings", "care_cert_mappings", "custom_mappings")
                for i in (after.get(f) or [])
                if i.get("confidence") in ("possible_evidence", "needs_review", "not_enough_evidence")
                and (i.get("status") or "pending") == "pending"]
        assert pend == [], f"possible items left pending: {len(pend)}"

    def test_no_mutation_on_422(self, admin):
        before = admin.get(f"{BASE}/review/{MEETING_ID}", timeout=60).json()["analysis"]
        snap = {f: [(i["id"], i.get("status")) for i in (before.get(f) or [])]
                for f in ("cqc_mappings", "care_cert_mappings", "custom_mappings")}
        r = admin.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action",
                       json={"confidence": "foo", "status": "bar"}, timeout=60)
        assert r.status_code == 422
        after = admin.get(f"{BASE}/review/{MEETING_ID}", timeout=60).json()["analysis"]
        snap2 = {f: [(i["id"], i.get("status")) for i in (after.get(f) or [])]
                 for f in ("cqc_mappings", "care_cert_mappings", "custom_mappings")}
        assert snap == snap2, "422 request mutated evidence state"


class TestRbacBackendStillEnforced:
    """HIGH FIX #1 backend counterpart — attendee still gets 403 (defence in depth)"""

    def test_attendee_bulk_action_403(self):
        s = login("user@supervision.com", "Staff123!")
        r = s.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action",
                   json={"confidence": "likely_evidence"}, timeout=60)
        assert r.status_code == 403, f"{r.status_code}: {r.text[:200]}"

    def test_attendee_bulk_action_403_on_rbac_meeting(self):
        """meeting c20802af... where Demo User is attendee"""
        s = login("user@supervision.com", "Staff123!")
        mid = "c20802af-17e3-4210-b497-13d09c9e67ec"
        r = s.post(f"{BASE}/review/{mid}/evidence/bulk-action",
                   json={"confidence": "likely_evidence"}, timeout=60)
        assert r.status_code in (403, 404), f"{r.status_code}: {r.text[:200]}"
