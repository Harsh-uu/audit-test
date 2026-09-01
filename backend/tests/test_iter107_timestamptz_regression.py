"""Iteration 107 — Phase 1 TEXT -> TIMESTAMPTZ migration regression suite.

Hammers every endpoint class that writes/reads a migrated timestamp column, looking
for runtime SQL type-inference failures (500s), broken string comparisons on decoded
timestamps, and ordering/validation regressions.

Run: cd /app/backend && python3 -m pytest tests/test_iter107_timestamptz_regression.py -n 0 -q
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
P = "TEST_iter107_"
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
        exp = NOW + timedelta(minutes=10)
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
        "SELECT id, email, role FROM users WHERE email = ANY($1::text[])",
        ["admin@supervision.com", "manager@supervision.com", "user@supervision.com",
         "jane@supervision.com"]))
    return {r["email"]: r["id"] for r in rows}


def created_meeting(session, title_suffix="", **extra):
    payload = {"title": f"{P}{title_suffix or uuid.uuid4().hex[:6]}",
               "date": NOW.date().isoformat(), "meeting_type": "supervision"}
    payload.update(extra)
    r = session.post(f"{BASE}/meetings/", json=payload, timeout=90)
    assert r.status_code in (200, 201), f"create meeting {r.status_code}: {r.text[:400]}"
    return r.json()


# ── AUTH: login / MFA / lockout / reset (users, login_attempts, password_reset_tokens)
class TestAuth:
    def test_admin_manager_staff_login_and_me(self, admin_s, manager_s, staff_s):
        for s, role in ((admin_s, "admin"), (manager_s, "manager"), (staff_s, "attendee")):
            me = s.get(f"{BASE}/auth/me", timeout=60)
            assert me.status_code == 200, me.text[:200]
            assert me.json()["role"] == role, me.json()

    def test_super_admin_login_and_orgs(self, super_s):
        me = super_s.get(f"{BASE}/auth/me", timeout=60)
        assert me.status_code == 200 and me.json()["role"] == "super_admin"

    def test_refresh_token(self, staff_s):
        r = staff_s.post(f"{BASE}/auth/refresh", timeout=60)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        assert staff_s.get(f"{BASE}/auth/me", timeout=60).status_code == 200

    def test_password_changed_at_is_real_timestamp(self):
        v = db(lambda c: c.fetchval(
            "SELECT password_changed_at FROM users WHERE email='admin@supervision.com'"))
        assert v is None or isinstance(v, datetime), type(v)

    def test_failed_logins_no_500_and_lockout_message(self):
        db(lambda c: c.execute("DELETE FROM login_attempts"))
        s = requests.Session()
        codes = []
        for _ in range(6):
            r = s.post(f"{BASE}/auth/login",
                       json={"email": "jane@supervision.com", "password": "WrongPass123!"},
                       timeout=90)
            codes.append(r.status_code)
            assert r.status_code != 500, f"500 on failed login: {r.text[:500]}"
        assert all(c in (401, 429) for c in codes), codes
        row = db(lambda c: c.fetchrow(
            "SELECT count, locked_until, updated_at FROM login_attempts WHERE identifier='jane@supervision.com'"))
        assert row is not None and row["count"] >= 5, dict(row) if row else None
        assert isinstance(row["locked_until"], datetime), type(row["locked_until"])
        assert isinstance(row["updated_at"], datetime), type(row["updated_at"])
        # correct password while locked -> 429 (lockout enforced from TIMESTAMPTZ value)
        r = s.post(f"{BASE}/auth/login",
                   json={"email": "jane@supervision.com", "password": "Jane123!"}, timeout=90)
        assert r.status_code == 429, f"expected lockout 429, got {r.status_code}: {r.text[:300]}"
        db(lambda c: c.execute("DELETE FROM login_attempts"))
        assert login("jane@supervision.com", "Jane123!") is not None

    def test_ip_wide_rate_limit_path_no_500(self):
        """rate_limit.py check_lockout + record_failed_attempt (the ::timestamptz CASE fix)."""
        db(lambda c: c.execute("DELETE FROM login_attempts"))
        s = requests.Session()
        for _ in range(4):
            r = s.post(f"{BASE}/auth/login",
                       json={"email": f"{P}ghost@example.com", "password": "Nope12345!"}, timeout=90)
            assert r.status_code == 401, f"{r.status_code}: {r.text[:300]}"
        rows = db(lambda c: c.fetch("SELECT identifier, locked_until FROM login_attempts"))
        assert any(r["identifier"].startswith("login_ip:") for r in rows), [r["identifier"] for r in rows]
        for r in rows:
            assert r["locked_until"] is None or isinstance(r["locked_until"], datetime)
        db(lambda c: c.execute("DELETE FROM login_attempts"))

    def test_forgot_password_creates_timestamptz_token_and_reset_works(self):
        db(lambda c: c.execute("DELETE FROM login_attempts"))
        r = requests.post(f"{BASE}/auth/forgot-password",
                          json={"email": "jane@supervision.com"}, timeout=90)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        row = db(lambda c: c.fetchrow(
            "SELECT token, expires_at, used FROM password_reset_tokens WHERE email='jane@supervision.com'"))
        assert row is not None, "no reset token persisted"
        assert isinstance(row["expires_at"], datetime), type(row["expires_at"])
        assert row["expires_at"] > datetime.now(timezone.utc)
        # use the token (policy needs >=10 chars, so use a temp pw and restore the hash after)
        old_hash = db(lambda c: c.fetchval(
            "SELECT password_hash FROM users WHERE email='jane@supervision.com'"))
        r2 = requests.post(f"{BASE}/auth/reset-password",
                           json={"token": row["token"], "new_password": "JaneReset123!"}, timeout=90)
        assert r2.status_code == 200, f"reset-password {r2.status_code}: {r2.text[:300]}"
        assert db(lambda c: c.fetchval(
            "SELECT used FROM password_reset_tokens WHERE token=$1", row["token"])) is True
        # login still works with the reset password
        assert login("jane@supervision.com", "JaneReset123!") is not None
        # password_changed_at written as a real timestamp
        pca = db(lambda c: c.fetchval(
            "SELECT password_changed_at FROM users WHERE email='jane@supervision.com'"))
        assert isinstance(pca, datetime), type(pca)
        db(lambda c: c.execute("DELETE FROM password_reset_tokens WHERE email='jane@supervision.com'"))
        db(lambda c: c.execute(
            "UPDATE users SET password_hash=$1 WHERE email='jane@supervision.com'", old_hash))
        assert login("jane@supervision.com", "Jane123!") is not None

    def test_expired_reset_token_rejected(self):
        tok = P + uuid.uuid4().hex
        db(lambda c: c.execute(
            "INSERT INTO password_reset_tokens (token, email, expires_at, used) VALUES ($1,$2,$3,FALSE)",
            tok, "jane@supervision.com", datetime.now(timezone.utc) - timedelta(hours=2)))
        r = requests.post(f"{BASE}/auth/reset-password",
                          json={"token": tok, "new_password": "JaneReset123!"}, timeout=90)
        assert r.status_code == 400, f"expected 400 expired, got {r.status_code}: {r.text[:300]}"
        assert "expired" in r.text.lower(), r.text[:300]
        db(lambda c: c.execute("DELETE FROM password_reset_tokens WHERE token=$1", tok))

    def test_expired_mfa_code_rejected(self):
        s = requests.Session()
        r = s.post(f"{BASE}/auth/login",
                   json={"email": "manager@supervision.com", "password": "Manager123!"}, timeout=90)
        assert r.status_code == 200 and r.json().get("requires_mfa"), r.text[:300]
        h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        db(lambda c: c.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email='manager@supervision.com'",
            h, datetime.now(timezone.utc) - timedelta(minutes=5)))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": r.json()["mfa_session"], "code": "123456"}, timeout=90)
        assert r2.status_code in (400, 401), f"expired MFA accepted or 500: {r2.status_code} {r2.text[:300]}"
        db(lambda c: c.execute("DELETE FROM login_attempts"))


# ── MEETINGS: create (rate-limited path) / list ordering / get / delete cascade
class TestMeetings:
    def test_rapid_creates_rate_limited_path(self, admin_s):
        ids_created = []
        for i in range(6):
            m = created_meeting(admin_s, f"rapid{i}")
            ids_created.append(m["id"])
        rows = db(lambda c: c.fetch(
            "SELECT id, created_at, updated_at FROM meetings WHERE id = ANY($1::text[])", ids_created))
        assert len(rows) == 6
        for r in rows:
            assert isinstance(r["created_at"], datetime) and isinstance(r["updated_at"], datetime)
        for mid in ids_created:
            assert admin_s.delete(f"{BASE}/meetings/{mid}", timeout=90).status_code == 200

    def test_list_ordering_desc_by_created_at(self, admin_s):
        r = admin_s.get(f"{BASE}/meetings/?limit=50", timeout=90)
        assert r.status_code == 200, r.text[:300]
        items = r.json()
        stamps = [i["created_at"] for i in items if i.get("created_at")]
        assert stamps == sorted(stamps, reverse=True), "meetings list not sorted created_at DESC"
        parsed = [datetime.fromisoformat(s) for s in stamps]
        assert parsed == sorted(parsed, reverse=True), "chronological order broken"

    def test_create_get_delete_cascade(self, admin_s, ids):
        m = created_meeting(admin_s, "cascade", attendee_ids=[ids["user@supervision.com"]])
        mid = m["id"]
        g = admin_s.get(f"{BASE}/meetings/{mid}", timeout=90)
        assert g.status_code == 200, g.text[:300]
        assert g.json()["id"] == mid
        # child rows with migrated timestamps
        tid, aid = P + uuid.uuid4().hex, P + uuid.uuid4().hex
        now = datetime.now(timezone.utc)

        async def seed(c):
            await c.execute(
                """INSERT INTO transcripts (id, meeting_id, org_id, text, speaker_text, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$6)""",
                tid, mid, ORG, "hello world transcript", "Speaker 1: hello world", now)
            await c.execute(
                """INSERT INTO analyses (id, meeting_id, org_id, summary, actions, risks,
                       cqc_mappings, care_cert_mappings, custom_mappings, pii_redactions,
                       achievements, learning_needs, created_at)
                   VALUES ($1,$2,$3,$4,'[]'::jsonb,'[]'::jsonb,'[]'::jsonb,'[]'::jsonb,'[]'::jsonb,
                           '[]'::jsonb,'[]'::jsonb,'[]'::jsonb,$5)""",
                aid, mid, ORG, "summary", now)
            await c.execute(
                """INSERT INTO audio_files (id, meeting_id, org_id, storage_path, upload_status,
                       processing_status, deletion_status, is_deleted, created_at)
                   VALUES ($1,$2,$3,$4,'uploaded','pending','active',FALSE,$5)""",
                P + uuid.uuid4().hex, mid, ORG, f"{P}nofile.webm", now)
            await c.execute(
                "INSERT INTO reviewer_comments (id, meeting_id, org_id, user_id, user_name, text, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                P + uuid.uuid4().hex, mid, ORG, "x", "x", "c", now)
            await c.execute(
                "INSERT INTO review_edits (id, meeting_id, org_id, action, detail, user_id, user_name, timestamp) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                P + uuid.uuid4().hex, mid, ORG, "summary_edited", "a -> b", "x", "x", now)
            await c.execute("UPDATE meetings SET transcript_id=$1, analysis_id=$2 WHERE id=$3", tid, aid, mid)
        db(seed)

        d = admin_s.delete(f"{BASE}/meetings/{mid}", timeout=120)
        assert d.status_code == 200, f"delete {d.status_code}: {d.text[:400]}"
        assert admin_s.get(f"{BASE}/meetings/{mid}", timeout=90).status_code == 404
        counts = db(lambda c: c.fetchrow(
            """SELECT (SELECT count(*) FROM transcripts WHERE meeting_id=$1) t,
                      (SELECT count(*) FROM analyses WHERE meeting_id=$1) a,
                      (SELECT count(*) FROM audio_files WHERE meeting_id=$1) au,
                      (SELECT count(*) FROM reviewer_comments WHERE meeting_id=$1) rc,
                      (SELECT count(*) FROM review_edits WHERE meeting_id=$1) re""", mid))
        assert dict(counts) == {"t": 0, "a": 0, "au": 0, "rc": 0, "re": 0}, dict(counts)


# ── RECORDING: notice/start/pause/resume/stop + events
class TestRecording:
    def test_full_recording_flow(self, admin_s):
        m = created_meeting(admin_s, "rec")
        mid = m["id"]
        try:
            r = admin_s.post(f"{BASE}/recording/{mid}/notice", timeout=90)
            assert r.status_code == 200, f"notice {r.status_code}: {r.text[:300]}"
            notice = db(lambda c: c.fetchval(
                "SELECT recording_notice_shown_at FROM meetings WHERE id=$1", mid))
            assert isinstance(notice, datetime), type(notice)

            assert admin_s.post(f"{BASE}/recording/{mid}/start", json={}, timeout=90).status_code == 200
            pause = admin_s.post(f"{BASE}/recording/{mid}/pause", json={}, timeout=90)
            assert pause.status_code == 200, pause.text[:300]
            pause_ts = pause.json()["timestamp"]
            res = admin_s.post(f"{BASE}/recording/{mid}/resume",
                               json={"pause_start": pause_ts}, timeout=90)
            assert res.status_code == 200, res.text[:300]
            stop = admin_s.post(f"{BASE}/recording/{mid}/stop", json={}, timeout=90)
            assert stop.status_code == 200, stop.text[:300]

            ev = admin_s.get(f"{BASE}/recording/{mid}/events", timeout=90)
            assert ev.status_code == 200, ev.text[:300]
            types = [e["type"] for e in ev.json().get("recording_events", [])]
            assert types == ["started", "paused", "resumed", "stopped"], types
            row = db(lambda c: c.fetchrow(
                "SELECT status, total_paused_duration_seconds, updated_at FROM meetings WHERE id=$1", mid))
            assert row["status"] == "stopped"
            assert isinstance(row["updated_at"], datetime)
        finally:
            admin_s.delete(f"{BASE}/meetings/{mid}", timeout=90)


# ── PROCESSING / JOBS: upload enqueues a job with TIMESTAMPTZ created_at
class TestProcessingJobs:
    def test_upload_creates_job_and_status_endpoint(self, admin_s):
        m = created_meeting(admin_s, "job")
        mid = m["id"]
        try:
            admin_s.post(f"{BASE}/recording/{mid}/notice", timeout=90)
            admin_s.post(f"{BASE}/recording/{mid}/start", json={}, timeout=90)
            admin_s.post(f"{BASE}/recording/{mid}/stop", json={}, timeout=90)
            up = admin_s.post(f"{BASE}/processing/{mid}/upload",
                              data=b"\x1a\x45\xdf\xa3" + b"0" * 2048,
                              headers={"Content-Type": "audio/webm"}, timeout=180)
            assert up.status_code == 200, f"upload {up.status_code}: {up.text[:400]}"
            job = db(lambda c: c.fetchrow(
                "SELECT id, status, created_at, updated_at FROM jobs WHERE meeting_id=$1", mid))
            assert job is not None, "no job row enqueued"
            assert isinstance(job["created_at"], datetime), type(job["created_at"])
            af = db(lambda c: c.fetchval("SELECT created_at FROM audio_files WHERE meeting_id=$1", mid))
            assert isinstance(af, datetime), type(af)
            # worker should claim/advance the job (ordered by created_at)
            import time
            statuses = set()
            for _ in range(10):
                time.sleep(3)
                st = admin_s.get(f"{BASE}/processing/{mid}/status", timeout=90)
                assert st.status_code == 200, f"status {st.status_code}: {st.text[:300]}"
                statuses.add(st.json().get("status"))
                jstat = db(lambda c: c.fetchval("SELECT status FROM jobs WHERE meeting_id=$1", mid))
                if jstat in ("done", "failed", "completed", "error"):
                    break
            jrow = db(lambda c: c.fetchrow(
                "SELECT status, updated_at, error FROM jobs WHERE meeting_id=$1", mid))
            print("job final:", dict(jrow), "api statuses:", statuses)
            assert jrow["status"] != "pending", "job never picked up by worker"
            assert isinstance(jrow["updated_at"], datetime)
        finally:
            db(lambda c: c.execute("DELETE FROM jobs WHERE meeting_id=$1", mid))
            admin_s.delete(f"{BASE}/meetings/{mid}", timeout=120)


# ── REVIEW: seeded review-ready meeting, edits/comments/audit/signoff/reopen
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
        # meeting first (FK parents), then children, then wire the ids back
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


class TestReviewFlow:
    def test_get_review(self, manager_s, review_meeting):
        r = manager_s.get(f"{BASE}/review/{review_meeting['id']}", timeout=90)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        assert r.json()["meeting"]["id"] == review_meeting["id"]

    def test_update_summary_writes_review_edit(self, manager_s, review_meeting):
        mid = review_meeting["id"]
        r = manager_s.put(f"{BASE}/review/{mid}/summary",
                          json={"summary": "Edited summary iter107"}, timeout=90)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        row = db(lambda c: c.fetchrow(
            "SELECT timestamp FROM review_edits WHERE meeting_id=$1 ORDER BY timestamp DESC LIMIT 1", mid))
        assert row is not None and isinstance(row["timestamp"], datetime), row
        le = db(lambda c: c.fetchval("SELECT last_edited_at FROM analyses WHERE meeting_id=$1", mid))
        assert isinstance(le, datetime), type(le)

    def test_speaker_text_edit_and_backup(self, manager_s, review_meeting):
        mid = review_meeting["id"]
        r = manager_s.patch(f"{BASE}/review/{mid}/speaker-text",
                            json={"speaker_text": "Manager: how are you\nStaff: fine, hand hygiene training done",
                                  "speaker_colors": {"Manager": "#111111"}}, timeout=90)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        row = db(lambda c: c.fetchrow(
            "SELECT speaker_text_edited_at, speaker_text_backup_at, updated_at FROM transcripts WHERE meeting_id=$1", mid))
        assert isinstance(row["speaker_text_edited_at"], datetime), dict(row)

    def test_evidence_update_writes_evidence_feedback(self, manager_s, review_meeting):
        mid = review_meeting["id"]
        r = manager_s.put(f"{BASE}/review/{mid}/evidence/cqc1",
                          json={"status": "accepted", "notes": "iter107"}, timeout=90)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        fb = db(lambda c: c.fetchrow(
            "SELECT timestamp FROM evidence_feedback WHERE meeting_id=$1 ORDER BY timestamp DESC LIMIT 1", mid))
        assert fb is not None, "no evidence_feedback row written"
        assert isinstance(fb["timestamp"], datetime), type(fb["timestamp"])

    def test_comments_post_and_get(self, manager_s, review_meeting):
        mid = review_meeting["id"]
        r = manager_s.post(f"{BASE}/review/{mid}/comments", json={"text": "iter107 comment"}, timeout=90)
        assert r.status_code in (200, 201), f"{r.status_code}: {r.text[:400]}"
        g = manager_s.get(f"{BASE}/review/{mid}/comments", timeout=90)
        assert g.status_code == 200, g.text[:300]
        assert any("iter107" in c.get("text", "") for c in g.json().get("comments", g.json() if isinstance(g.json(), list) else []))
        ts = db(lambda c: c.fetchval(
            "SELECT created_at FROM reviewer_comments WHERE meeting_id=$1 ORDER BY created_at DESC LIMIT 1", mid))
        assert isinstance(ts, datetime), type(ts)

    def test_audit_trail(self, manager_s, review_meeting):
        r = manager_s.get(f"{BASE}/review/{review_meeting['id']}/audit-trail", timeout=90)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:400]}"
        entries = r.json().get("entries", r.json() if isinstance(r.json(), list) else [])
        assert isinstance(entries, list) and len(entries) > 0, r.text[:400]

    def test_mark_reviewed_then_signoff_and_reopen(self, manager_s, staff_s, review_meeting):
        mid = review_meeting["id"]
        r1 = staff_s.post(f"{BASE}/review/{mid}/mark-reviewed", timeout=90)
        assert r1.status_code == 200, f"staff mark-reviewed {r1.status_code}: {r1.text[:300]}"
        r2 = manager_s.post(f"{BASE}/review/{mid}/mark-reviewed", timeout=90)
        assert r2.status_code == 200, f"manager mark-reviewed {r2.status_code}: {r2.text[:300]}"
        assert r2.json()["status"] == "reviewed", r2.json()
        so = manager_s.post(f"{BASE}/review/{mid}/signoff", timeout=120)
        assert so.status_code == 200, f"signoff {so.status_code}: {so.text[:400]}"
        row = db(lambda c: c.fetchrow(
            "SELECT status, audio_grace_period_started_at FROM meetings WHERE id=$1", mid))
        assert row["status"] == "signed_off", dict(row)
        assert isinstance(row["audio_grace_period_started_at"], datetime), type(row["audio_grace_period_started_at"])
        rr = staff_s.post(f"{BASE}/review/{mid}/request-reopen",
                          json={"reason": "iter107 reopen test"}, timeout=90)
        assert rr.status_code == 200, f"request-reopen {rr.status_code}: {rr.text[:400]}"
        req_at = db(lambda c: c.fetchval("SELECT reopen_requested_at FROM meetings WHERE id=$1", mid))
        assert isinstance(req_at, datetime), type(req_at)
        ar = manager_s.post(f"{BASE}/review/{mid}/approve-reopen", timeout=90)
        assert ar.status_code == 200, f"approve-reopen {ar.status_code}: {ar.text[:400]}"
        app_at = db(lambda c: c.fetchval("SELECT reopen_approved_at FROM meetings WHERE id=$1", mid))
        assert isinstance(app_at, datetime), type(app_at)

    def test_export_transcript_and_pdf(self, manager_s, review_meeting):
        mid = review_meeting["id"]
        for path in ("export-transcript", "export-pdf"):
            r = manager_s.get(f"{BASE}/review/{mid}/{path}", timeout=180)
            assert r.status_code == 200, f"{path} {r.status_code}: {r.text[:300]}"
            assert len(r.content) > 100, f"{path} empty payload"


# ── ORG STRUCTURE: settings / teams / invitations / branding
class TestOrg:
    def test_setting_team_crud_and_invite(self, admin_s):
        s = admin_s.post(f"{BASE}/org/settings", json={"name": P + "Branch"}, timeout=90)
        assert s.status_code in (200, 201), f"create setting {s.status_code}: {s.text[:400]}"
        sid = s.json().get("id") or s.json().get("setting", {}).get("id")
        assert sid, s.json()
        ts = db(lambda c: c.fetchrow("SELECT created_at, updated_at FROM org_settings WHERE id=$1", sid))
        assert isinstance(ts["created_at"], datetime), dict(ts)
        u = admin_s.put(f"{BASE}/org/settings/{sid}", json={"name": P + "Branch2"}, timeout=90)
        assert u.status_code == 200, f"update setting {u.status_code}: {u.text[:400]}"
        upd = db(lambda c: c.fetchval("SELECT updated_at FROM org_settings WHERE id=$1", sid))
        assert isinstance(upd, datetime), type(upd)

        t = admin_s.post(f"{BASE}/org/settings/{sid}/teams", json={"name": P + "Team"}, timeout=90)
        assert t.status_code in (200, 201), f"create team {t.status_code}: {t.text[:400]}"
        tid = t.json().get("id") or t.json().get("team", {}).get("id")
        assert isinstance(db(lambda c: c.fetchval("SELECT created_at FROM teams WHERE id=$1", tid)), datetime)
        assert admin_s.put(f"{BASE}/org/teams/{tid}", json={"name": P + "Team2"}, timeout=90).status_code == 200

        email = f"{P}invite_{uuid.uuid4().hex[:6]}@example.com"
        inv = admin_s.post(f"{BASE}/org/invite-user",
                           json={"name": P + "Invitee", "email": email, "role": "attendee",
                                 "password": "Invitee123!"}, timeout=120)
        assert inv.status_code in (200, 201), f"invite-user {inv.status_code}: {inv.text[:400]}"
        row = db(lambda c: c.fetchrow(
            """SELECT i.expires_at, i.created_at FROM invitations i
               JOIN users u ON u.id = i.user_id WHERE u.email=$1""", email))
        if row:
            assert isinstance(row["expires_at"], datetime), type(row["expires_at"])

        st = admin_s.get(f"{BASE}/org/structure", timeout=90)
        assert st.status_code == 200, st.text[:300]

        assert admin_s.delete(f"{BASE}/org/teams/{tid}", timeout=90).status_code == 200
        assert admin_s.delete(f"{BASE}/org/settings/{sid}", timeout=90).status_code == 200
        db(lambda c: c.execute(
            "DELETE FROM invitations WHERE user_id IN (SELECT id FROM users WHERE email=$1)", email))
        db(lambda c: c.execute("DELETE FROM users WHERE email=$1", email))

    def test_branding_get_put(self, admin_s):
        g = admin_s.get(f"{BASE}/org/branding", timeout=90)
        assert g.status_code == 200, g.text[:300]
        prev = g.json().get("primary_color")
        p = admin_s.put(f"{BASE}/org/branding", json={"primary_color": "#123456"}, timeout=90)
        assert p.status_code == 200, f"branding put {p.status_code}: {p.text[:400]}"
        upd = db(lambda c: c.fetchval("SELECT updated_at FROM organisations WHERE id=$1", ORG))
        assert isinstance(upd, datetime), type(upd)
        if prev:
            admin_s.put(f"{BASE}/org/branding", json={"primary_color": prev}, timeout=90)


# ── SCHEDULES + MEETING TYPES (schedules.start_date intentionally still TEXT)
class TestSchedules:
    def test_meeting_type_and_schedule_crud(self, admin_s, ids):
        mt = admin_s.post(f"{BASE}/schedules/meeting-types",
                          json={"name": P + "Type", "default_frequency": "monthly"}, timeout=90)
        assert mt.status_code in (200, 201), f"meeting-type {mt.status_code}: {mt.text[:400]}"
        mtid = mt.json().get("id") or mt.json().get("meeting_type", {}).get("id")
        assert isinstance(db(lambda c: c.fetchval("SELECT created_at FROM meeting_types WHERE id=$1", mtid)), datetime)

        sc = admin_s.post(f"{BASE}/schedules/",
                          json={"staff_user_id": ids["user@supervision.com"], "meeting_type_id": mtid,
                                "frequency": "monthly", "start_date": NOW.date().isoformat()}, timeout=90)
        assert sc.status_code in (200, 201), f"schedule create {sc.status_code}: {sc.text[:400]}"
        scid = sc.json().get("id") or sc.json().get("schedule", {}).get("id")
        row = db(lambda c: c.fetchrow("SELECT created_at, start_date FROM schedules WHERE id=$1", scid))
        assert isinstance(row["created_at"], datetime), type(row["created_at"])
        assert isinstance(row["start_date"], str), "schedules.start_date should still be TEXT"

        up = admin_s.put(f"{BASE}/schedules/{scid}",
                         json={"frequency": "weekly", "start_date": NOW.date().isoformat()}, timeout=90)
        assert up.status_code == 200, f"schedule update {up.status_code}: {up.text[:400]}"
        for path in ("/schedules/", "/schedules/due", "/schedules/meeting-types"):
            r = admin_s.get(f"{BASE}{path}", timeout=90)
            assert r.status_code == 200, f"{path} {r.status_code}: {r.text[:300]}"
        assert admin_s.delete(f"{BASE}/schedules/{scid}", timeout=90).status_code == 200
        assert admin_s.delete(f"{BASE}/schedules/meeting-types/{mtid}", timeout=90).status_code == 200


# ── PREP / FOCUS TOPICS (focus_topics.created_at still TEXT; meeting_prep migrated)
class TestPrep:
    def test_focus_topics_crud(self, admin_s):
        c = admin_s.post(f"{BASE}/prep/focus-topics",
                         json={"topic": P + "topic", "is_current": True,
                               "active_month": NOW.strftime("%Y-%m")}, timeout=90)
        assert c.status_code in (200, 201), f"focus-topic create {c.status_code}: {c.text[:400]}"
        tid = c.json().get("id") or c.json().get("topic", {}).get("id")
        lst = admin_s.get(f"{BASE}/prep/focus-topics", timeout=90)
        assert lst.status_code == 200, lst.text[:300]
        u = admin_s.put(f"{BASE}/prep/focus-topics/{tid}",
                        json={"topic": P + "topic2", "is_current": False,
                              "active_month": NOW.strftime("%Y-%m")}, timeout=90)
        assert u.status_code == 200, f"focus-topic update {u.status_code}: {u.text[:400]}"
        assert admin_s.delete(f"{BASE}/prep/focus-topics/{tid}", timeout=90).status_code == 200

    def test_prep_context_and_get(self, admin_s, ids):
        m = created_meeting(admin_s, "prep", attendee_ids=[ids["user@supervision.com"]])
        mid = m["id"]
        try:
            for path in (f"/prep/{mid}/context", f"/prep/{mid}"):
                r = admin_s.get(f"{BASE}{path}", timeout=120)
                assert r.status_code == 200, f"{path} {r.status_code}: {r.text[:400]}"
        finally:
            db(lambda c: c.execute("DELETE FROM meeting_prep WHERE meeting_id=$1", mid))
            admin_s.delete(f"{BASE}/meetings/{mid}", timeout=90)

    def test_prep_generate_and_share(self, admin_s, ids):
        m = created_meeting(admin_s, "prepgen", attendee_ids=[ids["user@supervision.com"]])
        mid = m["id"]
        try:
            g = admin_s.post(f"{BASE}/prep/{mid}/generate", json={"focus_topic": "hand hygiene"}, timeout=300)
            assert g.status_code == 200, f"prep generate {g.status_code}: {g.text[:400]}"
            # generation runs in a background task — poll gen_status
            import time
            row = None
            for _ in range(20):
                time.sleep(5)
                row = db(lambda c: c.fetchrow(
                    "SELECT gen_status, generated_at, created_at, updated_at FROM meeting_prep WHERE meeting_id=$1", mid))
                if row and row["gen_status"] in ("done", "failed"):
                    break
            assert row is not None, "no meeting_prep row"
            print("prep gen_status:", row["gen_status"])
            assert row["gen_status"] == "done", f"prep generation did not complete: {dict(row)}"
            assert isinstance(row["generated_at"], datetime), dict(row)
            sh = admin_s.post(f"{BASE}/prep/{mid}/share", timeout=120)
            assert sh.status_code == 200, f"prep share {sh.status_code}: {sh.text[:400]}"
            shared = db(lambda c: c.fetchval("SELECT shared_at FROM meeting_prep WHERE meeting_id=$1", mid))
            assert isinstance(shared, datetime), type(shared)
        finally:
            db(lambda c: c.execute("DELETE FROM meeting_prep WHERE meeting_id=$1", mid))
            admin_s.delete(f"{BASE}/meetings/{mid}", timeout=90)


# ── ADMIN / DASHBOARD / STANDARDS
class TestAdminSurface:
    def test_read_endpoints(self, admin_s):
        for path in ("/dashboard/", "/admin/users", "/admin/standards", "/admin/standards/documents",
                     "/admin/stats", "/admin/team-insights", "/admin/people-stats",
                     "/admin/meetings-brief", "/admin/template", "/admin/team-insights/registers"):
            r = admin_s.get(f"{BASE}{path}", timeout=180)
            assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:300]}"

    def test_admin_user_lifecycle(self, admin_s):
        email = f"{P}u_{uuid.uuid4().hex[:6]}@example.com"
        c = admin_s.post(f"{BASE}/admin/users",
                         json={"email": email, "name": P + "User", "role": "attendee",
                               "password": "UserPass123!"}, timeout=120)
        assert c.status_code in (200, 201), f"create user {c.status_code}: {c.text[:400]}"
        uid = c.json().get("id") or c.json().get("user", {}).get("id")
        row = db(lambda c2: c2.fetchrow("SELECT created_at, updated_at FROM users WHERE id=$1", uid))
        assert isinstance(row["created_at"], datetime), dict(row)
        u = admin_s.put(f"{BASE}/admin/users/{uid}", json={"name": P + "User2"}, timeout=90)
        assert u.status_code == 200, f"update user {u.status_code}: {u.text[:400]}"
        rp = admin_s.post(f"{BASE}/admin/users/{uid}/reset-password",
                          json={"new_password": "NewUserPass123!"}, timeout=90)
        assert rp.status_code == 200, f"reset-password {rp.status_code}: {rp.text[:400]}"
        pca = db(lambda c2: c2.fetchval("SELECT password_changed_at FROM users WHERE id=$1", uid))
        assert isinstance(pca, datetime), type(pca)
        d = admin_s.delete(f"{BASE}/admin/users/{uid}", timeout=90)
        assert d.status_code in (200, 204), f"delete user {d.status_code}: {d.text[:300]}"
        db(lambda c2: c2.execute("DELETE FROM users WHERE email=$1", email))

    def test_standards_document_upload(self, admin_s):
        content = ("Standard 1: Person-centred care. Staff must provide dignity.\n"
                   "Standard 2: Safeguarding. Staff must report concerns.\n") * 3
        files = {"file": (f"{P}std.txt", content.encode(), "text/plain")}
        r = admin_s.post(f"{BASE}/admin/standards/upload", files=files,
                         data={"type": "custom", "name": P + "doc"}, timeout=300)
        assert r.status_code in (200, 201, 400, 422), f"upload {r.status_code}: {r.text[:400]}"
        if r.status_code in (200, 201):
            doc_id = r.json().get("document_id") or r.json().get("id")
            row = db(lambda c: c.fetchrow(
                "SELECT created_at, parsed_at FROM standards_documents WHERE id=$1", doc_id))
            if row:
                assert isinstance(row["created_at"], datetime), dict(row)
            if doc_id:
                admin_s.delete(f"{BASE}/admin/standards/documents/{doc_id}", timeout=120)
        else:
            print("standards upload rejected (non-500):", r.status_code, r.text[:200])


# ── SUPER ADMIN: orgs list/create/update/invite/delete
class TestSuperAdmin:
    def test_org_lifecycle(self, super_s):
        lst = super_s.get(f"{BASE}/super-admin/orgs", timeout=120)
        assert lst.status_code == 200, f"orgs list {lst.status_code}: {lst.text[:300]}"
        suffix = uuid.uuid4().hex[:8]
        c = super_s.post(f"{BASE}/super-admin/orgs",
                         json={"name": f"{P}Org_{suffix}", "jurisdiction": "england"}, timeout=120)
        assert c.status_code in (200, 201), f"create org {c.status_code}: {c.text[:400]}"
        oid = c.json().get("id") or c.json().get("org", {}).get("id")
        row = db(lambda x: x.fetchrow("SELECT created_at, updated_at FROM organisations WHERE id=$1", oid))
        assert isinstance(row["created_at"], datetime), dict(row)
        p = super_s.patch(f"{BASE}/super-admin/orgs/{oid}",
                          json={"name": f"{P}Org2_{suffix}"}, timeout=120)
        assert p.status_code == 200, f"patch org {p.status_code}: {p.text[:400]}"
        assert isinstance(db(lambda x: x.fetchval(
            "SELECT updated_at FROM organisations WHERE id=$1", oid)), datetime)
        email = f"{P}orgadmin_{uuid.uuid4().hex[:6]}@example.com"
        inv = super_s.post(f"{BASE}/super-admin/orgs/{oid}/invite",
                           json={"email": email, "name": P + "OrgAdmin"}, timeout=120)
        assert inv.status_code in (200, 201), f"org invite {inv.status_code}: {inv.text[:400]}"
        irow = db(lambda x: x.fetchrow(
            """SELECT i.expires_at, i.created_at FROM invitations i
               JOIN users u ON u.id = i.user_id WHERE u.email=$1""", email))
        assert irow is not None and isinstance(irow["expires_at"], datetime), irow and dict(irow)
        d = super_s.delete(f"{BASE}/super-admin/orgs/{oid}", timeout=180)
        assert d.status_code == 200, f"delete org {d.status_code}: {d.text[:400]}"
        db(lambda x: x.execute(
            "DELETE FROM invitations WHERE user_id IN (SELECT id FROM users WHERE email=$1)", email))
        db(lambda x: x.execute("DELETE FROM users WHERE email=$1", email))
        db(lambda x: x.execute("DELETE FROM organisations WHERE id=$1", oid))


# ── Residue check
def test_no_test_residue():
    counts = db(lambda c: c.fetchrow(
        """SELECT (SELECT count(*) FROM meetings WHERE title LIKE $1) m,
                  (SELECT count(*) FROM transcripts WHERE id LIKE $1) t,
                  (SELECT count(*) FROM analyses WHERE id LIKE $1) a,
                  (SELECT count(*) FROM users WHERE email LIKE $1) u,
                  (SELECT count(*) FROM organisations WHERE name LIKE $1) o,
                  (SELECT count(*) FROM invitations i2 JOIN users u2 ON u2.id=i2.user_id
                   WHERE u2.email LIKE $1) i""", P + "%"))
    print("residue:", dict(counts))
    assert sum(dict(counts).values()) == 0, dict(counts)
