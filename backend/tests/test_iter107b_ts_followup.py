"""Iteration 107b — follow-up to the TEXT->TIMESTAMPTZ regression suite.

Re-runs the 6 cases that failed in test_iter107_timestamptz_regression.py with
corrected response-shape / role assumptions, so we can separate real product
regressions from test-script bugs. Also isolates the ONE confirmed regression:
PATCH /api/review/{id}/speaker-text -> 500 (empty-string written to the
now-TIMESTAMPTZ transcripts.speaker_text_backup_at, routers/review.py:1075).

Run: cd /app/backend && python3 -m pytest tests/test_iter107b_ts_followup.py -n 0 -q
"""
import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values, load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")

BE = dotenv_values("/app/backend/.env")
FE = dotenv_values("/app/frontend/.env")
BASE = FE["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]

ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"
P = "TEST_iter107b_"
NOW = datetime.now(timezone.utc)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _db(fn):
    conn = await asyncpg.connect(DSN)
    try:
        return await fn(conn)
    finally:
        await conn.close()


def db(fn):
    return _run(_db(fn))


def login(email, password):
    db(lambda c: c.execute("DELETE FROM login_attempts"))
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=90)
    assert r.status_code == 200, f"login {email} failed {r.status_code}: {r.text[:300]}"
    data = r.json()
    if data.get("requires_mfa"):
        h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        exp = datetime.now(timezone.utc) + timedelta(minutes=10)
        db(lambda c: c.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
            h, exp, email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=90)
        assert r2.status_code == 200, f"mfa {email} failed {r2.status_code}: {r2.text[:300]}"
    me = s.get(f"{BASE}/auth/me", timeout=60)
    assert me.status_code == 200, me.text[:300]
    return s


@pytest.fixture(scope="session")
def admin_s():
    return login("admin@supervision.com", "Admin123!")


@pytest.fixture(scope="session")
def manager_s():
    return login("manager@supervision.com", "Manager123!")


@pytest.fixture(scope="session")
def staff_s():
    return login("user@supervision.com", "Staff123!")


@pytest.fixture(scope="session")
def super_s():
    return login("superadmin@1two.one", "NewPass123!")


@pytest.fixture(scope="session")
def ids():
    rows = db(lambda c: c.fetch(
        "SELECT id, email FROM users WHERE email = ANY($1::text[])",
        ["admin@supervision.com", "manager@supervision.com", "user@supervision.com"]))
    return {r["email"]: r["id"] for r in rows}


@pytest.fixture(scope="class")
def review_meeting(ids):
    mid = P + uuid.uuid4().hex
    tid = P + "t" + uuid.uuid4().hex
    aid = P + "a" + uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    attendees = [
        {"user_id": ids["user@supervision.com"], "name": "Staff", "role": "attendee",
         "present": True, "reviewed": False, "reviewed_at": None},
        {"user_id": ids["manager@supervision.com"], "name": "Manager", "role": "manager",
         "present": True, "reviewed": False, "reviewed_at": None},
    ]

    async def seed(c):
        await c.execute(
            """INSERT INTO meetings (id, org_id, title, date, status, attendees,
                   created_by, created_by_name, sign_off_manager_id,
                   sign_off_manager_name, recording_events, paused_periods, pii_redactions,
                   total_paused_duration_seconds, audio_deletion_status, created_at, updated_at)
               VALUES ($1,$2,$3,$4,'in_review',$5::jsonb,$6,'Admin',$7,'Manager',
                       '[]'::jsonb,'[]'::jsonb,'[]'::jsonb,0,'none',$8,$8)""",
            mid, ORG, P + "review", now.date().isoformat(), json.dumps(attendees),
            ids["admin@supervision.com"], ids["manager@supervision.com"], now)
        await c.execute(
            """INSERT INTO transcripts (id, meeting_id, org_id, text, speaker_text, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$6)""",
            tid, mid, ORG, "Manager: how are you. Staff: fine, hand hygiene training done.",
            "Speaker 1: how are you\nSpeaker 2: fine, hand hygiene training done", now)
        await c.execute(
            """INSERT INTO analyses (id, meeting_id, org_id, summary, actions, risks,
                   cqc_mappings, care_cert_mappings, custom_mappings, pii_redactions,
                   achievements, learning_needs, created_at)
               VALUES ($1,$2,$3,$4,$5::jsonb,'[]'::jsonb,$6::jsonb,'[]'::jsonb,'[]'::jsonb,
                       '[]'::jsonb,'[]'::jsonb,'[]'::jsonb,$7)""",
            aid, mid, ORG, "Initial summary",
            json.dumps([{"id": "act1", "text": "Book training", "owner": "Staff", "completed": False}]),
            json.dumps([{"id": "cqc1", "standard_id": "s1", "reference": "R1", "name": "Safe care",
                         "confidence": "likely_evidence",
                         "evidence_summary": "hand hygiene training done",
                         "status": "pending"}]),
            now)
        await c.execute(
            "UPDATE meetings SET transcript_id=$1, analysis_id=$2 WHERE id=$3", tid, aid, mid)
    db(seed)
    yield {"id": mid, "transcript_id": tid, "analysis_id": aid}

    async def cleanup(c):
        await c.execute("DELETE FROM evidence_feedback WHERE meeting_id=$1", mid)
        await c.execute("DELETE FROM audit_logs WHERE meeting_id=$1", mid)
        await c.execute("DELETE FROM reviewer_comments WHERE meeting_id=$1", mid)
        await c.execute("DELETE FROM review_edits WHERE meeting_id=$1", mid)
        await c.execute("DELETE FROM meetings WHERE id=$1", mid)
        await c.execute("DELETE FROM transcripts WHERE id=$1", tid)
        await c.execute("DELETE FROM analyses WHERE id=$1", aid)
    db(cleanup)


class TestReviewFollowUp:
    # shape-corrected: GET /review/{id} returns the meeting fields at top level
    def test_get_review_shape(self, manager_s, review_meeting):
        r = manager_s.get(f"{BASE}/review/{review_meeting['id']}", timeout=90)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        body = r.json()
        top = body.get("meeting", body)
        assert top.get("id") == review_meeting["id"], list(body.keys())[:15]
        # timestamps must survive as ISO strings usable by the frontend
        assert isinstance(top.get("created_at"), str) and "T" in top["created_at"], top.get("created_at")

    # CONFIRMED REGRESSION: empty string -> TIMESTAMPTZ speaker_text_backup_at
    def test_speaker_text_edit_no_500(self, manager_s, review_meeting):
        mid = review_meeting["id"]
        r = manager_s.patch(f"{BASE}/review/{mid}/speaker-text",
                            json={"speaker_text": "Manager: how are you\nStaff: fine",
                                  "speaker_colors": {"Manager": "#111111"}}, timeout=90)
        assert r.status_code != 500, (
            "REGRESSION: routers/review.py:1075 passes '' for speaker_text_backup_at "
            "(now TIMESTAMPTZ) -> asyncpg InvalidDatetimeFormatError")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        row = db(lambda c: c.fetchrow(
            "SELECT speaker_text_edited_at, speaker_text_backup_at FROM transcripts WHERE meeting_id=$1", mid))
        assert isinstance(row["speaker_text_edited_at"], datetime), dict(row)

    # second edit: backup_at now has a real prior value
    def test_speaker_text_second_edit(self, manager_s, review_meeting):
        mid = review_meeting["id"]
        r = manager_s.patch(f"{BASE}/review/{mid}/speaker-text",
                            json={"speaker_text": "Manager: hello\nStaff: good"}, timeout=90)
        assert r.status_code == 200, f"second edit {r.status_code}: {r.text[:400]}"

    def test_comments_post_and_get(self, manager_s, review_meeting):
        mid = review_meeting["id"]
        r = manager_s.post(f"{BASE}/review/{mid}/comments", json={"text": "iter107b comment"}, timeout=90)
        assert r.status_code in (200, 201), f"{r.status_code}: {r.text[:400]}"
        g = manager_s.get(f"{BASE}/review/{mid}/comments", timeout=90)
        assert g.status_code == 200, g.text[:300]
        body = g.json()
        items = body if isinstance(body, list) else body.get("comments", [])
        assert any("iter107b" in (c.get("text") or "") for c in items), str(items)[:300]
        ts = db(lambda c: c.fetchval(
            "SELECT created_at FROM reviewer_comments WHERE meeting_id=$1 ORDER BY created_at DESC LIMIT 1", mid))
        assert isinstance(ts, datetime), type(ts)

    def test_audit_trail_events(self, manager_s, review_meeting):
        r = manager_s.get(f"{BASE}/review/{review_meeting['id']}/audit-trail", timeout=90)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        body = r.json()
        events = body if isinstance(body, list) else body.get("events", body.get("entries", []))
        assert isinstance(events, list) and len(events) > 0, str(body)[:300]
        for e in events:
            assert isinstance(e.get("timestamp"), str) and "T" in e["timestamp"], e

    # role-corrected: manager REQUESTS re-open, attendee APPROVES
    def test_signoff_then_reopen(self, manager_s, staff_s, review_meeting):
        mid = review_meeting["id"]
        assert staff_s.post(f"{BASE}/review/{mid}/mark-reviewed", timeout=90).status_code == 200
        r2 = manager_s.post(f"{BASE}/review/{mid}/mark-reviewed", timeout=90)
        assert r2.status_code == 200, r2.text[:300]
        so = manager_s.post(f"{BASE}/review/{mid}/signoff", timeout=120)
        assert so.status_code == 200, f"signoff {so.status_code}: {so.text[:400]}"
        grace = db(lambda c: c.fetchval(
            "SELECT audio_grace_period_started_at FROM meetings WHERE id=$1", mid))
        assert isinstance(grace, datetime), type(grace)
        rr = manager_s.post(f"{BASE}/review/{mid}/request-reopen",
                            json={"reason": "iter107b reopen"}, timeout=90)
        assert rr.status_code == 200, f"request-reopen {rr.status_code}: {rr.text[:400]}"
        assert isinstance(db(lambda c: c.fetchval(
            "SELECT reopen_requested_at FROM meetings WHERE id=$1", mid)), datetime)
        ar = staff_s.post(f"{BASE}/review/{mid}/approve-reopen", timeout=90)
        assert ar.status_code == 200, f"approve-reopen {ar.status_code}: {ar.text[:400]}"
        assert isinstance(db(lambda c: c.fetchval(
            "SELECT reopen_approved_at FROM meetings WHERE id=$1", mid)), datetime)


class TestSuperAdminFollowUp:
    # email-case corrected (backend lowercases emails) + invitation timestamps
    def test_org_invite_lifecycle(self, super_s):
        suffix = uuid.uuid4().hex[:8]
        c = super_s.post(f"{BASE}/super-admin/orgs",
                         json={"name": f"{P}Org_{suffix}", "jurisdiction": "england"}, timeout=120)
        assert c.status_code in (200, 201), f"create org {c.status_code}: {c.text[:400]}"
        oid = c.json().get("id") or c.json().get("org", {}).get("id")
        email = f"{P}orgadmin_{uuid.uuid4().hex[:6]}@example.com".lower()
        try:
            inv = super_s.post(f"{BASE}/super-admin/orgs/{oid}/invite",
                               json={"email": email, "name": P + "OrgAdmin"}, timeout=120)
            assert inv.status_code in (200, 201), f"org invite {inv.status_code}: {inv.text[:400]}"
            irow = db(lambda x: x.fetchrow(
                """SELECT i.expires_at, i.created_at FROM invitations i
                   JOIN users u ON u.id = i.user_id WHERE lower(u.email)=$1""", email))
            assert irow is not None, "invitation row not created"
            assert isinstance(irow["expires_at"], datetime), dict(irow)
            assert isinstance(irow["created_at"], datetime), dict(irow)
            d = super_s.delete(f"{BASE}/super-admin/orgs/{oid}", timeout=180)
            assert d.status_code == 200, f"delete org {d.status_code}: {d.text[:400]}"
        finally:
            db(lambda x: x.execute(
                "DELETE FROM invitations WHERE user_id IN (SELECT id FROM users WHERE lower(email)=$1)", email))
            db(lambda x: x.execute("DELETE FROM users WHERE lower(email)=$1", email))
            db(lambda x: x.execute("DELETE FROM organisations WHERE id=$1", oid))


class TestTimestampReads:
    """Extra read surfaces that render/sort migrated timestamps."""

    def test_meetings_list_and_date_filters(self, admin_s):
        r = admin_s.get(f"{BASE}/meetings/", timeout=120)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        items = body if isinstance(body, list) else body.get("meetings", [])
        frm = (NOW - timedelta(days=365)).date().isoformat()
        to = (NOW + timedelta(days=1)).date().isoformat()
        for q in (f"?date_from={frm}&date_to={to}", "?status=signed_off", f"?date_from={frm}"):
            rr = admin_s.get(f"{BASE}/meetings/{q}", timeout=120)
            assert rr.status_code == 200, f"{q} -> {rr.status_code}: {rr.text[:300]}"
        # created_at descending
        cas = [m.get("created_at") for m in items if m.get("created_at")]
        assert cas == sorted(cas, reverse=True), cas[:5]

    def test_dashboard_and_admin_reads(self, admin_s):
        for path in ("/dashboard/", "/admin/users", "/admin/stats", "/admin/team-insights",
                     "/org/settings", "/org/teams", "/org/invitations", "/schedules/",
                     "/prep/focus-topics", "/portfolio/"):
            r = admin_s.get(f"{BASE}{path}", timeout=180)
            assert r.status_code in (200, 404), f"{path} -> {r.status_code}: {r.text[:300]}"
            if r.status_code == 404:
                print(f"NOTE {path} -> 404 (route may not exist)")


def test_residue_cleanup():
    counts = db(lambda c: c.fetchrow(
        """SELECT (SELECT count(*) FROM meetings WHERE id LIKE $1 OR title LIKE $1) m,
                  (SELECT count(*) FROM transcripts WHERE id LIKE $1) t,
                  (SELECT count(*) FROM analyses WHERE id LIKE $1) a,
                  (SELECT count(*) FROM organisations WHERE name LIKE $1) o""",
        "TEST_iter107%"))
    print("residue before cleanup:", dict(counts))

    async def purge(c):
        await c.execute("DELETE FROM transcripts WHERE id LIKE 'TEST_iter107%'")
        await c.execute("DELETE FROM analyses WHERE id LIKE 'TEST_iter107%'")
        await c.execute("DELETE FROM meetings WHERE id LIKE 'TEST_iter107%' OR title LIKE 'TEST_iter107%'")
        await c.execute("DELETE FROM organisations WHERE name LIKE 'TEST_iter107%'")
    db(purge)
    after = db(lambda c: c.fetchrow(
        """SELECT (SELECT count(*) FROM meetings WHERE id LIKE $1 OR title LIKE $1) m,
                  (SELECT count(*) FROM organisations WHERE name LIKE $1) o""", "TEST_iter107%"))
    assert sum(dict(after).values()) == 0, dict(after)
