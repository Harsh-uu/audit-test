"""SEC-001 IDOR fix verification for review export/audit endpoints.

Endpoints under test (all must enforce per-user authorization, not just org scoping):
  GET /api/review/{meeting_id}/export-pdf
  GET /api/review/{meeting_id}/export-transcript
  GET /api/review/{meeting_id}/audit-trail
  GET /api/review/{meeting_id}            (sanity / no regression)
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

be = dotenv_values("/app/backend/.env")
fe = dotenv_values("/app/frontend/.env")
BASE = fe["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = be["DATABASE_URL"]

TARGET_MEETING = "0383953a-9a17-4f7f-9924-ed5ec30b42b6"

CREDS = {
    "jane": ("jane@supervision.com", "Jane123!"),
    "staff": ("user@supervision.com", "Staff123!"),
    "manager": ("manager@supervision.com", "Manager123!"),
}


async def _force_mfa(mail):
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, mail)
    await conn.close()


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=90)
    if r.status_code != 200:
        pytest.fail(f"Login failed for {email}: {r.status_code} {r.text[:300]}")
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_force_mfa(email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=90)
        if r2.status_code != 200:
            pytest.fail(f"MFA verify failed for {email}: {r2.status_code} {r2.text[:300]}")
    me = s.get(f"{BASE}/auth/me", timeout=60)
    if me.status_code != 200:
        pytest.fail(f"/auth/me failed for {email}: {me.status_code} {me.text[:200]}")
    return s, me.json()


@pytest.fixture(scope="session")
def jane():
    return _login(*CREDS["jane"])


@pytest.fixture(scope="session")
def staff():
    return _login(*CREDS["staff"])


@pytest.fixture(scope="session")
def manager():
    return _login(*CREDS["manager"])


@pytest.fixture(scope="session")
def meeting_row():
    async def _get():
        conn = await asyncpg.connect(DSN, ssl="require")
        row = await conn.fetchrow(
            "SELECT id, org_id, status, attendees, shared_with, created_by FROM meetings WHERE id=$1",
            TARGET_MEETING)
        await conn.close()
        return dict(row) if row else None
    row = asyncio.run(_get())
    if not row:
        pytest.fail(f"Target meeting {TARGET_MEETING} not present in DB")
    return row


def _ids(val):
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            return []
    if not isinstance(val, list):
        return []
    return [x.get("user_id") for x in val if isinstance(x, dict)]


# ── Preconditions ────────────────────────────────────────────────────────────
class TestPreconditions:
    def test_jane_same_org_but_not_on_meeting(self, jane, meeting_row):
        s, me = jane
        assert me["role"] == "attendee", f"jane role changed: {me['role']}"
        assert me["org_id"] == meeting_row["org_id"], "jane not in same org as target meeting"
        assert me["id"] not in _ids(meeting_row["attendees"])
        assert me["id"] not in _ids(meeting_row["shared_with"])
        assert me["id"] != (meeting_row["created_by"] or "")

    def test_staff_is_attendee_and_meeting_signed_off(self, staff, meeting_row):
        s, me = staff
        assert meeting_row["status"] == "signed_off", f"status={meeting_row['status']}"
        assert me["id"] in _ids(meeting_row["attendees"]), "staff user is not an attendee"


# ── SEC-001: IDOR must be blocked ────────────────────────────────────────────
class TestIdorBlocked:
    def test_export_pdf_blocked(self, jane):
        s, _ = jane
        r = s.get(f"{BASE}/review/{TARGET_MEETING}/export-pdf", timeout=120)
        assert r.status_code == 404, f"IDOR: got {r.status_code}, len={len(r.content)}"
        assert "not found" in r.text.lower()

    def test_export_pdf_with_transcript_blocked(self, jane):
        s, _ = jane
        r = s.get(f"{BASE}/review/{TARGET_MEETING}/export-pdf?include_transcript=true", timeout=120)
        assert r.status_code == 404, f"IDOR: got {r.status_code}, len={len(r.content)}"

    def test_export_transcript_blocked(self, jane):
        s, _ = jane
        r = s.get(f"{BASE}/review/{TARGET_MEETING}/export-transcript", timeout=120)
        assert r.status_code == 404, f"IDOR: got {r.status_code}, len={len(r.content)}"

    def test_audit_trail_blocked_not_empty_200(self, jane):
        s, _ = jane
        r = s.get(f"{BASE}/review/{TARGET_MEETING}/audit-trail", timeout=120)
        assert r.status_code == 404, (
            f"IDOR: got {r.status_code} body={r.text[:300]} "
            "(catch-all must not swallow the 404 into 200 empty events)")

    def test_review_data_blocked(self, jane):
        s, _ = jane
        r = s.get(f"{BASE}/review/{TARGET_MEETING}", timeout=120)
        assert r.status_code == 404, f"IDOR: got {r.status_code}"

    def test_unauthenticated_blocked(self):
        for path in ["export-pdf", "export-transcript", "audit-trail", ""]:
            url = f"{BASE}/review/{TARGET_MEETING}/{path}".rstrip("/")
            r = requests.get(url, timeout=60)
            assert r.status_code in (401, 403), f"{path}: got {r.status_code}"


# ── Regression: legitimate attendee access ───────────────────────────────────
class TestAttendeeAccess:
    def test_export_pdf_ok(self, staff):
        s, _ = staff
        r = s.get(f"{BASE}/review/{TARGET_MEETING}/export-pdf", timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert r.content[:4] == b"%PDF", "response is not a PDF"
        assert len(r.content) > 1000

    def test_export_transcript_ok(self, staff):
        s, _ = staff
        r = s.get(f"{BASE}/review/{TARGET_MEETING}/export-transcript", timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert len(r.content) > 100

    def test_audit_trail_ok(self, staff):
        s, _ = staff
        r = s.get(f"{BASE}/review/{TARGET_MEETING}/audit-trail", timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        body = r.json()
        assert isinstance(body.get("events"), list)
        assert len(body["events"]) > 0, "audit trail returned empty events for legitimate attendee"

    def test_review_data_ok(self, staff):
        s, _ = staff
        r = s.get(f"{BASE}/review/{TARGET_MEETING}", timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        data = r.json()
        assert data.get("id") == TARGET_MEETING
        assert "_id" not in data


# ── Regression: manager access ───────────────────────────────────────────────
class TestManagerAccess:
    def test_export_pdf_ok(self, manager):
        s, _ = manager
        r = s.get(f"{BASE}/review/{TARGET_MEETING}/export-pdf", timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert r.content[:4] == b"%PDF"

    def test_export_transcript_ok(self, manager):
        s, _ = manager
        r = s.get(f"{BASE}/review/{TARGET_MEETING}/export-transcript", timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_audit_trail_ok(self, manager):
        s, _ = manager
        r = s.get(f"{BASE}/review/{TARGET_MEETING}/audit-trail", timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert len(r.json().get("events", [])) > 0

    def test_review_data_ok(self, manager):
        s, _ = manager
        r = s.get(f"{BASE}/review/{TARGET_MEETING}", timeout=180)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_nonexistent_meeting_404(self, manager):
        s, _ = manager
        bogus = "00000000-0000-0000-0000-000000000000"
        for path in ["export-pdf", "export-transcript", "audit-trail"]:
            r = s.get(f"{BASE}/review/{bogus}/{path}", timeout=90)
            assert r.status_code == 404, f"{path}: got {r.status_code}"
