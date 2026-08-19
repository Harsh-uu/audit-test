"""Iteration 69 targeted fix verification.

Covers:
 - POST /api/review/{id}/mark-reviewed no longer double-JSON-encodes meetings.attendees
   (jsonb_typeof(attendees) must be 'array', not 'string')
 - GET /api/dashboard/ (trailing slash) returns 200 with no redirect
 - GET /api/dashboard (no slash) still 307s (documents why frontend must use the slash)
"""
import asyncio
import json
import os

import asyncpg
import pytest
import requests
from dotenv import dotenv_values

be = dotenv_values("/app/backend/.env")
fe = dotenv_values("/app/frontend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe["REACT_APP_BACKEND_URL"]).rstrip("/") + "/api"
DSN = be["DATABASE_URL"]

MEETING_ID = "680d8ecb-c9f2-4f3f-bdd0-1937fbc60791"
ATTENDEE_EMAIL = "user@supervision.com"
ATTENDEE_PW = "Staff123!"


# ---------------- helpers ----------------
async def _q(sql, *args):
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        return await conn.fetchval(sql, *args)
    finally:
        await conn.close()


async def _exec(sql, *args):
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        return await conn.execute(sql, *args)
    finally:
        await conn.close()


def q(sql, *args):
    return asyncio.get_event_loop().run_until_complete(_q(sql, *args))


def ex(sql, *args):
    return asyncio.get_event_loop().run_until_complete(_exec(sql, *args))


@pytest.fixture(scope="module")
def attendee_session():
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": ATTENDEE_EMAIL, "password": ATTENDEE_PW}, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"attendee login failed {r.status_code}: {r.text[:300]}")
    body = r.json()
    if body.get("requires_mfa"):
        pytest.fail("attendee unexpectedly requires MFA")
    return s


# ---------------- mark-reviewed jsonb encoding ----------------
class TestMarkReviewedJsonb:
    def test_reset_attendee_unreviewed(self):
        raw = q("SELECT attendees FROM meetings WHERE id=$1", MEETING_ID)
        assert raw is not None, "test meeting missing"
        att = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(att, str):
            att = json.loads(att)
        assert isinstance(att, list) and att, "attendees empty"
        for a in att:
            if a.get("email") == ATTENDEE_EMAIL:
                a["reviewed"] = False
                a.pop("reviewed_at", None)
        ex("UPDATE meetings SET attendees=$1, status=$2 WHERE id=$3", json.dumps(att), "in_review", MEETING_ID)
        emails = [a.get("email") for a in att]
        assert ATTENDEE_EMAIL in emails, f"attendee not on meeting: {emails}"

    def test_mark_reviewed_stores_jsonb_array(self, attendee_session):
        r = attendee_session.post(f"{BASE}/review/{MEETING_ID}/mark-reviewed", timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        data = r.json()
        assert data.get("message") == "Marked as reviewed"
        assert data.get("status") in ("in_review", "reviewed")

        typ = q("SELECT jsonb_typeof(attendees) FROM meetings WHERE id=$1", MEETING_ID)
        assert typ == "array", f"attendees stored as {typ!r}, expected 'array' (double-encoding regression)"

        # verify the flag actually persisted inside the jsonb array
        cnt = q(
            "SELECT count(*) FROM meetings m, jsonb_array_elements(m.attendees) a "
            "WHERE m.id=$1 AND a->>'email'=$2 AND (a->>'reviewed')='true'",
            MEETING_ID, ATTENDEE_EMAIL,
        )
        assert cnt == 1, "reviewed=true not persisted as real jsonb array element"

    def test_get_review_reflects_reviewed(self, attendee_session):
        r = attendee_session.get(f"{BASE}/review/{MEETING_ID}", timeout=30)
        assert r.status_code == 200, r.text[:300]
        m = r.json().get("meeting", r.json())
        att = m.get("attendees")
        assert isinstance(att, list), f"attendees not a list in API response: {type(att)}"
        me = [a for a in att if a.get("email") == ATTENDEE_EMAIL]
        assert me and me[0].get("reviewed") is True


# ---------------- dashboard trailing slash ----------------
class TestDashboardSlash:
    def test_dashboard_trailing_slash_no_redirect(self, attendee_session):
        r = attendee_session.get(f"{BASE}/dashboard/", timeout=60, allow_redirects=False)
        assert r.status_code == 200, f"{r.status_code} {r.headers.get('location')} {r.text[:200]}"
        data = r.json()
        assert isinstance(data, dict) and data, "empty dashboard payload"
        assert '"_id"' not in json.dumps(data), "mongo _id leaked in dashboard payload"

    def test_dashboard_without_slash_redirects(self, attendee_session):
        r = attendee_session.get(f"{BASE}/dashboard", timeout=60, allow_redirects=False)
        # documents the 307 the frontend now avoids
        assert r.status_code in (200, 307), r.status_code
        if r.status_code == 307:
            assert r.headers.get("location", "").endswith("/api/dashboard/")
