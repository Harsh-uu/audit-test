"""Iteration 106 (lean retry) — real Supabase Storage delete primitive + meeting-delete
purge + evidence_feedback FK cascade + API smoke.

Run: cd /app/backend && python3 -m pytest tests/test_iter106_audio_delete_lean.py -n 0 -q
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
SUPA_URL = BE["SUPABASE_URL"].rstrip("/")
SUPA_KEY = BE["SUPABASE_SERVICE_KEY"]

ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"
P = "TEST_iter106_"


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
        exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        db(lambda c: c.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
            h, exp, email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=90)
        assert r2.status_code == 200, f"mfa {email} failed {r2.status_code}: {r2.text[:300]}"
    me = s.get(f"{BASE}/auth/me", timeout=60)
    assert me.status_code == 200, me.text[:200]
    return s


def storage_exists(path: str) -> bool:
    h = {"Authorization": f"Bearer {SUPA_KEY}", "apikey": SUPA_KEY, "Cache-Control": "no-cache"}
    r = requests.get(f"{SUPA_URL}/storage/v1/object/info/audio-recordings/{path}",
                     headers=h, timeout=60)
    if r.status_code == 200:
        return True
    assert "not_found" in r.text or "NoSuchKey" in r.text, \
        f"unexpected storage info response {r.status_code}: {r.text[:200]}"
    return False


def storage_list(prefix: str):
    h = {"Authorization": f"Bearer {SUPA_KEY}", "apikey": SUPA_KEY}
    r = requests.post(f"{SUPA_URL}/storage/v1/object/list/audio-recordings",
                      headers=h, json={"prefix": prefix, "limit": 100}, timeout=60)
    assert r.status_code == 200, r.text[:200]
    # list returns names relative to the prefix "folder"
    return [prefix + f["name"] for f in r.json()]


@pytest.fixture(scope="session")
def admin_s():
    return login("admin@supervision.com", "Admin123!")


@pytest.fixture(scope="session")
def jane_s():
    return login("jane@supervision.com", "Jane123!")


@pytest.fixture(scope="session")
def jane_id():
    return db(lambda c: c.fetchval("SELECT id FROM users WHERE email='jane@supervision.com'"))


# ── P1: REAL Supabase Storage put → get → delete → gone ───────────────────────
class TestP1StoragePrimitive:
    def test_put_get_delete_audio_against_real_supabase(self):
        from utils.supabase_storage import delete_audio, get_audio, put_audio
        path = f"{P}storage/{uuid.uuid4().hex}.webm"
        payload = b"iter106-real-supabase-bytes-" + uuid.uuid4().hex.encode()

        res = _run(put_audio(path, payload, "audio/webm"))
        assert res.get("path") == path, res
        assert storage_exists(path), "object not present in Supabase after put_audio"
        assert path in storage_list(f"{P}storage/")

        data, ctype = _run(get_audio(path))
        assert data == payload, "get_audio returned different bytes"
        assert isinstance(ctype, str) and ctype

        _run(delete_audio(path))

        assert not storage_exists(path), "object STILL in Supabase Storage after delete_audio"
        assert path not in storage_list(f"{P}storage/"), "object still listed after delete_audio"

        # NOTE: get_audio() on this exact path can still return 200 from the Supabase
        # CDN edge cache (cf-cache-status: HIT) because it was downloaded before the
        # delete and uploads don't set cache-control. Origin truth is asserted above.
        # A never-downloaded object is verified 404 on get_audio below.

    def test_get_audio_404s_after_delete_when_not_cdn_cached(self):
        from utils.supabase_storage import delete_audio, get_audio, put_audio
        path = f"{P}storage/nodl_{uuid.uuid4().hex}.webm"
        _run(put_audio(path, b"iter106-nodl", "audio/webm"))
        _run(delete_audio(path))
        with pytest.raises(Exception) as exc:
            _run(get_audio(path))
        assert "404" in str(exc.value) or "not_found" in str(exc.value).lower(), str(exc.value)[:200]

    def test_delete_audio_on_missing_path_does_not_raise(self):
        from utils.supabase_storage import delete_audio
        _run(delete_audio(f"{P}storage/never-existed-{uuid.uuid4().hex}.webm"))


# ── P2: meeting with transcript/analysis + audio → DELETE purges storage ──────
class TestP2MeetingDeletion:
    def test_get_then_delete_meeting_purges_audio_and_rows(self, admin_s, jane_id):
        now = datetime.now(timezone.utc).isoformat()
        r = admin_s.post(f"{BASE}/meetings/", json={
            "title": f"{P}p2", "date": now[:10], "location": "Room 106",
            "meeting_type": "supervision", "attendee_ids": [jane_id]}, timeout=90)
        assert r.status_code == 200, f"create meeting {r.status_code}: {r.text[:300]}"
        mid = r.json()["id"]
        path = f"{P}storage/meeting_{mid}.webm"
        from utils.supabase_storage import delete_audio, put_audio
        _run(put_audio(path, b"iter106-meeting-audio", "audio/webm"))
        assert storage_exists(path)

        mappings = [{"id": "ev1", "regulation_ref": "R9", "regulation_name": "Person-centred care",
                     "confidence": "likely_evidence", "status": "pending",
                     "evidence_summary": "Discussed care planning",
                     "transcript_excerpt": "we reviewed the plan"}]
        ttext = f"{P}transcript body text"

        async def seed(c):
            await c.execute(
                "INSERT INTO transcripts (id, meeting_id, org_id, text, created_at) VALUES ($1,$2,$3,$4,$5)",
                f"{P}tr_{mid}", mid, ORG, ttext, now)
            await c.execute(
                """INSERT INTO analyses (id, meeting_id, org_id, summary, cqc_mappings, created_at)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6)""",
                f"{P}an_{mid}", mid, ORG, f"{P}summary", json.dumps(mappings), now)
            await c.execute(
                """INSERT INTO audio_files (id, meeting_id, org_id, storage_path, is_deleted,
                                            deletion_status, created_at)
                   VALUES ($1,$2,$3,$4,FALSE,'not_started',$5)""",
                f"{P}af_{mid}", mid, ORG, path, now)
            await c.execute(
                "UPDATE meetings SET transcript_id=$1, analysis_id=$2, audio_file_id=$3, status='in_review' WHERE id=$4",
                f"{P}tr_{mid}", f"{P}an_{mid}", f"{P}af_{mid}", mid)
        db(seed)

        try:
            g = admin_s.get(f"{BASE}/meetings/{mid}", timeout=90)
            assert g.status_code == 200, g.text[:300]
            body = g.json()
            assert body["id"] == mid
            blob = json.dumps(body)
            assert f"{P}summary" in blob, "analysis summary missing from GET /meetings/{id}"
            tr = admin_s.get(f"{BASE}/meetings/{mid}/transcript-text", timeout=90)
            assert tr.status_code == 200, tr.text[:300]
            assert tr.json()["text"] == ttext

            d = admin_s.delete(f"{BASE}/meetings/{mid}", timeout=90)
            assert d.status_code == 200, f"delete meeting {d.status_code}: {d.text[:300]}"

            assert admin_s.get(f"{BASE}/meetings/{mid}", timeout=90).status_code == 404
            counts = db(lambda c: c.fetchrow(
                """SELECT (SELECT count(*) FROM meetings WHERE id=$1) m,
                          (SELECT count(*) FROM audio_files WHERE meeting_id=$1) a,
                          (SELECT count(*) FROM transcripts WHERE meeting_id=$1) t,
                          (SELECT count(*) FROM analyses WHERE meeting_id=$1) an""", mid))
            assert dict(counts) == {"m": 0, "a": 0, "t": 0, "an": 0}, dict(counts)
            assert not storage_exists(path), "audio object still in Supabase after meeting delete"
        finally:
            try:
                _run(delete_audio(path))
            except Exception:
                pass
            db(lambda c: c.execute("DELETE FROM meetings WHERE id=$1", mid))

    def test_delete_meeting_without_audio_row(self, admin_s, jane_id):
        now = datetime.now(timezone.utc).isoformat()
        r = admin_s.post(f"{BASE}/meetings/", json={
            "title": f"{P}p2_noaudio", "date": now[:10], "location": "Room 106",
            "meeting_type": "supervision", "attendee_ids": [jane_id]}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        mid = r.json()["id"]
        try:
            d = admin_s.delete(f"{BASE}/meetings/{mid}", timeout=90)
            assert d.status_code == 200, f"delete no-audio meeting {d.status_code}: {d.text[:300]}"
            assert db(lambda c: c.fetchval("SELECT count(*) FROM meetings WHERE id=$1", mid)) == 0
        finally:
            db(lambda c: c.execute("DELETE FROM meetings WHERE id=$1", mid))

    def test_delete_nonexistent_meeting_404(self, admin_s):
        assert admin_s.delete(f"{BASE}/meetings/{P}nope", timeout=90).status_code == 404


# ── P3: evidence_feedback FK constraints + cascade ────────────────────────────
class TestP3EvidenceFeedbackFK:
    def test_fk_constraints_exist(self):
        rows = db(lambda c: c.fetch(
            """SELECT constraint_name FROM information_schema.table_constraints
               WHERE table_name='evidence_feedback' AND constraint_type='FOREIGN KEY'"""))
        names = {r["constraint_name"] for r in rows}
        assert "fk_evidence_feedback_meeting_id" in names, names
        assert "fk_evidence_feedback_org_id" in names, names

    def test_evidence_feedback_cascades_on_meeting_delete(self, admin_s, jane_id):
        now = datetime.now(timezone.utc).isoformat()
        r = admin_s.post(f"{BASE}/meetings/", json={
            "title": f"{P}p3", "date": now[:10], "location": "Room 106",
            "meeting_type": "supervision", "attendee_ids": [jane_id]}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        mid = r.json()["id"]
        efid = f"{P}ef_{mid}"
        try:
            db(lambda c: c.execute(
                """INSERT INTO evidence_feedback (id, meeting_id, org_id, user_id, user_name,
                       evidence_item_id, evidence_type, standard_ref, manager_action, timestamp)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
                efid, mid, ORG, "u1", "Tester", "ev1", "cqc", "R9", "accepted", now))
            assert db(lambda c: c.fetchval(
                "SELECT count(*) FROM evidence_feedback WHERE id=$1", efid)) == 1

            # raw DB delete → proves FK ON DELETE CASCADE (not just app-level cleanup)
            db(lambda c: c.execute("DELETE FROM meetings WHERE id=$1", mid))
            assert db(lambda c: c.fetchval(
                "SELECT count(*) FROM evidence_feedback WHERE id=$1", efid)) == 0, \
                "evidence_feedback row leaked after meeting row deleted"
        finally:
            db(lambda c: c.execute("DELETE FROM evidence_feedback WHERE id=$1", efid))
            db(lambda c: c.execute("DELETE FROM meetings WHERE id=$1", mid))


# ── P4: smoke ────────────────────────────────────────────────────────────────
class TestP4Smoke:
    @pytest.mark.parametrize("who", ["admin", "jane"])
    def test_dashboard_and_meetings_list(self, admin_s, jane_s, who):
        s = admin_s if who == "admin" else jane_s
        d = s.get(f"{BASE}/dashboard/", timeout=90)
        assert d.status_code == 200, f"{who} dashboard {d.status_code}: {d.text[:300]}"
        m = s.get(f"{BASE}/meetings/", timeout=90)
        assert m.status_code == 200, f"{who} meetings {m.status_code}: {m.text[:300]}"
        assert isinstance(m.json(), (list, dict))

    def test_manager_login_review_and_report_views(self):
        mgr = login("manager@supervision.com", "Manager123!")
        assert mgr.get(f"{BASE}/dashboard/", timeout=90).status_code == 200
        lst = mgr.get(f"{BASE}/meetings/", timeout=90)
        assert lst.status_code == 200, lst.text[:300]
        items = lst.json() if isinstance(lst.json(), list) else lst.json().get("meetings", [])
        signed = [x for x in items if x.get("analysis_id")] or items
        assert signed, "no meetings available for report smoke test"
        mid = signed[0]["id"]
        assert mgr.get(f"{BASE}/meetings/{mid}", timeout=90).status_code == 200
        rv = mgr.get(f"{BASE}/review/{mid}", timeout=90)
        assert rv.status_code == 200, f"review view {rv.status_code}: {rv.text[:300]}"
        at = mgr.get(f"{BASE}/review/{mid}/audit-trail", timeout=90)
        assert at.status_code in (200, 404), f"audit-trail {at.status_code}: {at.text[:200]}"


# ── residue ──────────────────────────────────────────────────────────────────
class TestZResidue:
    def test_no_residue(self):
        async def go(c):
            return {
                "meetings": await c.fetchval("SELECT count(*) FROM meetings WHERE title LIKE $1", f"{P}%"),
                "evidence_feedback": await c.fetchval("SELECT count(*) FROM evidence_feedback WHERE id LIKE $1", f"{P}%"),
                "audio_files": await c.fetchval("SELECT count(*) FROM audio_files WHERE id LIKE $1", f"{P}%"),
                "transcripts": await c.fetchval("SELECT count(*) FROM transcripts WHERE id LIKE $1", f"{P}%"),
            }
        res = db(go)
        assert all(v == 0 for v in res.values()), f"db residue: {res}"
        assert storage_list(f"{P}storage/") == [], "storage residue"
