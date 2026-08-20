"""iteration_87 — backend tests for POST /api/review/{meeting_id}/evidence/bulk-action

Covers: RBAC (403 attendee), 404 unknown meeting, 409 locked meeting,
bulk-accept of likely/possible tiers (pending-only), idempotency,
single summarised audit-trail entry, and individual-evidence-PUT regression.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

be = dotenv_values("/app/backend/.env")
fe = dotenv_values("/app/frontend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe["REACT_APP_BACKEND_URL"]).rstrip("/") + "/api"
DSN = be["DATABASE_URL"]

MEETING_ID = "2f1cc088-0687-48b9-9f40-1dabb5285640"  # in_review, Test Company org
FIELDS = ["cqc_mappings", "care_cert_mappings", "custom_mappings"]
POSSIBLE = {"possible_evidence", "needs_review", "not_enough_evidence"}


# ── DB helpers ───────────────────────────────────────────────────────────────
async def _mfa_override(mail):
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, mail)
    await conn.close()


def login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_mfa_override(email))
        r2 = s.post(f"{BASE}/auth/verify-mfa", json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=60)
        if r2.status_code != 200:
            pytest.fail(f"mfa failed for {email}: {r2.status_code} {r2.text[:300]}")
    return s


def _lst(v):
    if v is None:
        return []
    return json.loads(v) if isinstance(v, str) else v


async def _seed(meeting_id, mode="mix", status=None):
    """mode=mix -> all pending, but one likely pre-accepted + one possible pre-rejected per field."""
    conn = await asyncpg.connect(DSN, ssl="require")
    m = await conn.fetchrow("SELECT analysis_id FROM meetings WHERE id=$1", meeting_id)
    a = await conn.fetchrow("SELECT * FROM analyses WHERE id=$1", m["analysis_id"])
    snapshot = {}
    for f in FIELDS:
        items = _lst(a[f])
        for i in range(len(items)):
            items[i]["status"] = "pending"
        if mode == "mix":
            done = {"l": 0, "p": 0}
            for i, it in enumerate(items):
                c = it.get("confidence")
                if c == "likely_evidence" and not done["l"]:
                    items[i]["status"] = "accepted"; done["l"] = 1
                elif c in POSSIBLE and not done["p"]:
                    items[i]["status"] = "rejected"; done["p"] = 1
        await conn.execute(f"UPDATE analyses SET {f}=$1::jsonb WHERE id=$2", json.dumps(items), m["analysis_id"])
        snapshot[f] = items
    if status:
        await conn.execute("UPDATE meetings SET status=$1 WHERE id=$2", status, meeting_id)
    await conn.close()
    return snapshot


async def _set_meeting_status(meeting_id, status):
    conn = await asyncpg.connect(DSN, ssl="require")
    await conn.execute("UPDATE meetings SET status=$1 WHERE id=$2", status, meeting_id)
    await conn.close()


@pytest.fixture(scope="module")
def admin():
    return login("admin@supervision.com", "Admin123!")


@pytest.fixture(scope="module")
def attendee():
    return login("user@supervision.com", "Staff123!")


@pytest.fixture(autouse=True)
def seeded():
    """Reset evidence to the 'mix' baseline and meeting back to in_review before each test."""
    asyncio.run(_seed(MEETING_ID, "mix", status="in_review"))
    yield
    asyncio.run(_set_meeting_status(MEETING_ID, "in_review"))


def counts(mapping_lists):
    out = {}
    for f in FIELDS:
        for it in mapping_lists.get(f) or []:
            out[(it.get("confidence"), it.get("status") or "pending")] = \
                out.get((it.get("confidence"), it.get("status") or "pending"), 0) + 1
    return out


# ── Health / baseline ────────────────────────────────────────────────────────
class TestBaseline:
    def test_review_get_works(self, admin):
        r = admin.get(f"{BASE}/review/{MEETING_ID}", timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert "analysis" in d and d["analysis"] is not None
        assert isinstance(d["analysis"]["cqc_mappings"], list)


# ── RBAC & error handling ────────────────────────────────────────────────────
class TestBulkActionRBAC:
    def test_attendee_forbidden(self, attendee):
        r = attendee.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action",
                          json={"confidence": "likely_evidence", "status": "accepted"}, timeout=60)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text[:300]}"

    def test_unauthenticated_rejected(self):
        r = requests.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action",
                          json={"confidence": "likely_evidence"}, timeout=60)
        assert r.status_code in (401, 403), r.status_code

    def test_unknown_meeting_404(self, admin):
        r = admin.post(f"{BASE}/review/00000000-0000-0000-0000-000000000000/evidence/bulk-action",
                       json={"confidence": "likely_evidence"}, timeout=60)
        assert r.status_code == 404, f"{r.status_code}: {r.text[:200]}"

    def test_locked_meeting_409(self, admin):
        asyncio.run(_set_meeting_status(MEETING_ID, "signed_off"))
        try:
            r = admin.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action",
                           json={"confidence": "likely_evidence"}, timeout=60)
            assert r.status_code == 409, f"{r.status_code}: {r.text[:200]}"
        finally:
            asyncio.run(_set_meeting_status(MEETING_ID, "in_review"))

    def test_missing_confidence_422(self, admin):
        r = admin.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action", json={}, timeout=60)
        assert r.status_code == 422, f"{r.status_code}: {r.text[:200]}"


# ── Core behaviour ───────────────────────────────────────────────────────────
class TestBulkAcceptLikely:
    def test_accept_all_likely(self, admin):
        before = admin.get(f"{BASE}/review/{MEETING_ID}", timeout=60).json()["analysis"]
        expected = sum(
            1 for f in FIELDS for it in (before.get(f) or [])
            if it.get("confidence") == "likely_evidence" and (it.get("status") or "pending") == "pending")
        pre_rejected = {it["id"] for f in FIELDS for it in (before.get(f) or []) if it.get("status") == "rejected"}
        assert expected > 0, "seed produced no pending likely items"

        r = admin.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action",
                       json={"confidence": "likely_evidence", "status": "accepted"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["updated_count"] == expected, f"{d['updated_count']} != {expected}"
        assert "message" in d
        for f in FIELDS:
            assert f in d and isinstance(d[f], list), f"{f} missing from response"

        # response payload: no pending likely left, rejected untouched
        c = counts(d)
        assert c.get(("likely_evidence", "pending"), 0) == 0
        for f in FIELDS:
            for it in d[f]:
                if it["id"] in pre_rejected:
                    assert it["status"] == "rejected", "pre-rejected item was overwritten"

        # persistence via GET
        after = admin.get(f"{BASE}/review/{MEETING_ID}", timeout=60).json()["analysis"]
        ca = counts(after)
        assert ca.get(("likely_evidence", "pending"), 0) == 0
        # possible tier untouched
        assert ca.get(("possible_evidence", "pending"), 0) == \
            counts(before).get(("possible_evidence", "pending"), 0)

    def test_second_call_is_noop(self, admin):
        r1 = admin.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action",
                        json={"confidence": "likely_evidence"}, timeout=60)
        assert r1.status_code == 200
        assert r1.json()["updated_count"] > 0
        r2 = admin.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action",
                        json={"confidence": "likely_evidence"}, timeout=60)
        assert r2.status_code == 200
        assert r2.json()["updated_count"] == 0, "repeat bulk-accept should update nothing"


class TestBulkAcceptPossible:
    def test_accept_all_possible_includes_legacy_aliases(self, admin):
        before = admin.get(f"{BASE}/review/{MEETING_ID}", timeout=60).json()["analysis"]
        expected = sum(
            1 for f in FIELDS for it in (before.get(f) or [])
            if it.get("confidence") in POSSIBLE and (it.get("status") or "pending") == "pending")
        assert expected > 0
        likely_pending_before = counts(before).get(("likely_evidence", "pending"), 0)

        r = admin.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action",
                       json={"confidence": "possible_evidence", "status": "accepted"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["updated_count"] == expected

        after = admin.get(f"{BASE}/review/{MEETING_ID}", timeout=60).json()["analysis"]
        ca = counts(after)
        for conf in POSSIBLE:
            assert ca.get((conf, "pending"), 0) == 0
        # likely tier untouched
        assert ca.get(("likely_evidence", "pending"), 0) == likely_pending_before


# ── Audit trail ──────────────────────────────────────────────────────────────
class TestAuditTrail:
    def test_single_summary_entry(self, admin):
        pre = admin.get(f"{BASE}/review/{MEETING_ID}/audit-trail", timeout=60)
        assert pre.status_code == 200, pre.text[:300]
        pre_items = pre.json() if isinstance(pre.json(), list) else pre.json().get("events", [])
        n_before = len(pre_items)

        r = admin.post(f"{BASE}/review/{MEETING_ID}/evidence/bulk-action",
                       json={"confidence": "likely_evidence"}, timeout=60)
        assert r.status_code == 200
        updated = r.json()["updated_count"]
        assert updated > 1, "need >1 item to prove a single summary entry"

        post = admin.get(f"{BASE}/review/{MEETING_ID}/audit-trail", timeout=60).json()
        post_items = post if isinstance(post, list) else post.get("events", [])
        delta = len(post_items) - n_before
        assert delta == 1, f"expected exactly 1 new audit entry, got {delta}"
        blob = json.dumps(post_items)
        assert "bulk-accepted" in blob, f"summary text missing from audit trail: {blob[:500]}"
        assert f"{updated} likely evidence" in blob, f"count/label missing: {blob[:500]}"


# ── Regression: individual evidence update still works ───────────────────────
class TestIndividualEvidenceRegression:
    def test_single_accept_and_reject(self, admin):
        analysis = admin.get(f"{BASE}/review/{MEETING_ID}", timeout=60).json()["analysis"]
        target = next(it for it in analysis["cqc_mappings"] if (it.get("status") or "pending") == "pending")
        eid = target["id"]

        r = admin.put(f"{BASE}/review/{MEETING_ID}/evidence/{eid}", json={"status": "accepted"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        after = admin.get(f"{BASE}/review/{MEETING_ID}", timeout=60).json()["analysis"]
        assert next(i for i in after["cqc_mappings"] if i["id"] == eid)["status"] == "accepted"

        r = admin.put(f"{BASE}/review/{MEETING_ID}/evidence/{eid}", json={"status": "rejected"}, timeout=60)
        assert r.status_code == 200
        after = admin.get(f"{BASE}/review/{MEETING_ID}", timeout=60).json()["analysis"]
        assert next(i for i in after["cqc_mappings"] if i["id"] == eid)["status"] == "rejected"

    def test_attendee_cannot_update_individual(self, attendee):
        r = attendee.get(f"{BASE}/review/{MEETING_ID}", timeout=60)
        if r.status_code != 200:
            pytest.skip("attendee has no access to this meeting")
        analysis = r.json()["analysis"]
        eid = analysis["cqc_mappings"][0]["id"]
        r2 = attendee.put(f"{BASE}/review/{MEETING_ID}/evidence/{eid}", json={"status": "accepted"}, timeout=60)
        assert r2.status_code == 403, f"{r2.status_code}: {r2.text[:200]}"
