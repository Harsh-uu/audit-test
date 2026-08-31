"""Iteration 105 — audio GDPR storage-deletion wiring + evidence_feedback cascade.

Covers:
  P1 sign-off → grace_period → sweep → REAL Supabase object gone, DB flags set,
     transcript/analysis 100% untouched
  P2 DELETE /api/meetings/{id} purges audio from storage (incl. already-deleted case)
  P3 DELETE /api/super-admin/orgs/{id} purges audio + evidence_feedback + all org data
  P4 regression: report/transcript/evidence views, bulk-accept-evidence,
     mark-reviewed/sign-off for a meeting with NO audio
  P5 negative: storage delete failure must NOT mark DB as deleted (retryable)

Run: cd /app/backend && python3 -m pytest tests/test_iter105_audio_gdpr_delete.py -n 0 -q
(-n 0 mandatory: shared-account MFA override + login_attempts truncation.)
"""
import asyncio
import json
import os
import sys
import time
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
P = "TEST_iter105_"


# ── infra helpers ─────────────────────────────────────────────────────────────
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
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text[:300]}"
    data = r.json()
    if data.get("requires_mfa"):
        h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        db(lambda c: c.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
            h, exp, email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=90)
        assert r2.status_code == 200, f"mfa failed {r2.status_code}: {r2.text[:300]}"
    me = s.get(f"{BASE}/auth/me", timeout=60)
    assert me.status_code == 200
    return s


# ── REAL Supabase Storage helpers (cache-busted, so no CDN false positives) ───
def storage_exists(path: str) -> bool:
    """True iff the object really exists (uses the /info endpoint, never CDN cached)."""
    h = {"Authorization": f"Bearer {SUPA_KEY}", "apikey": SUPA_KEY, "Cache-Control": "no-cache"}
    r = requests.get(f"{SUPA_URL}/storage/v1/object/info/audio-recordings/{path}", headers=h, timeout=60)
    if r.status_code == 200:
        return True
    body = r.text
    assert "not_found" in body or "NoSuchKey" in body, f"unexpected storage info response {r.status_code}: {body[:200]}"
    return False


def upload_real_audio(path: str, payload: bytes = b"iter105-audio-bytes"):
    from utils.supabase_storage import put_audio
    _run(put_audio(path, payload, "audio/webm"))
    assert storage_exists(path), f"seed upload failed for {path}"
    return path


def remove_real_audio(path: str):
    from utils.supabase_storage import delete_audio
    try:
        _run(delete_audio(path))
    except Exception:
        pass


# ── seeding ───────────────────────────────────────────────────────────────────
MAPPINGS = [
    {"id": "ev1", "regulation_ref": "R9", "regulation_name": "Person-centred care",
     "confidence": "likely_evidence", "status": "pending",
     "evidence_summary": "Discussed care planning", "transcript_excerpt": "we reviewed the plan"},
    {"id": "ev2", "regulation_ref": "R12", "regulation_name": "Safe care",
     "confidence": "likely_evidence", "status": "pending",
     "evidence_summary": "Medication competency checked", "transcript_excerpt": "meds signed off"},
]

TRANSCRIPT_TEXT = "iter105 permanent record transcript — must survive audio deletion. " * 5
SUMMARY_TEXT = "iter105 permanent analysis summary — must survive audio deletion."


def create_meeting(admin_s, attendee_ids, title_suffix, with_audio=True, audio_payload=None):
    now = datetime.now(timezone.utc).isoformat()
    r = admin_s.post(f"{BASE}/meetings/", json={
        "title": f"{P}{title_suffix}", "date": now[:10], "location": "Room 105",
        "meeting_type": "supervision", "attendee_ids": attendee_ids}, timeout=90)
    assert r.status_code == 200, f"create meeting failed {r.status_code}: {r.text[:300]}"
    mid = r.json()["id"]
    tid, aid, fid = f"{P}tr_{mid[:8]}", f"{P}an_{mid[:8]}", f"{P}af_{mid[:8]}"
    storage_path = None
    if with_audio:
        storage_path = f"{P}storage/{mid}.webm"
        upload_real_audio(storage_path, audio_payload or b"iter105-audio-bytes")

    async def seed(c):
        await c.execute(
            "INSERT INTO transcripts (id, meeting_id, org_id, text, created_at) VALUES ($1,$2,$3,$4,$5)",
            tid, mid, ORG, TRANSCRIPT_TEXT, now)
        await c.execute(
            """INSERT INTO analyses (id, meeting_id, org_id, summary, cqc_mappings, created_at)
               VALUES ($1,$2,$3,$4,$5::jsonb,$6)""",
            aid, mid, ORG, SUMMARY_TEXT, json.dumps(MAPPINGS), now)
        if with_audio:
            await c.execute(
                """INSERT INTO audio_files (id, meeting_id, org_id, storage_path, is_deleted,
                                            deletion_status, created_at)
                   VALUES ($1,$2,$3,$4,FALSE,'not_started',$5)""",
                fid, mid, ORG, storage_path, now)
        await c.execute(
            "UPDATE meetings SET transcript_id=$1, analysis_id=$2, audio_file_id=$3, status='in_review' WHERE id=$4",
            tid, aid, fid if with_audio else None, mid)
    db(seed)
    return {"mid": mid, "tid": tid, "aid": aid, "fid": fid, "path": storage_path}


def cleanup_meeting(m):
    db(lambda c: c.execute("DELETE FROM meetings WHERE id=$1", m["mid"]))
    if m.get("path"):
        remove_real_audio(m["path"])


@pytest.fixture(scope="session")
def admin_s():
    return login("admin@supervision.com", "Admin123!")


@pytest.fixture(scope="session")
def manager_s():
    return login("manager@supervision.com", "Manager123!")


@pytest.fixture(scope="session")
def jane_s():
    return login("jane@supervision.com", "Jane123!")


@pytest.fixture(scope="session")
def super_s():
    return login("superadmin@1two.one", "NewPass123!")


@pytest.fixture(scope="session")
def jane_id():
    return db(lambda c: c.fetchval("SELECT id FROM users WHERE email='jane@supervision.com'"))


def run_sweep():
    """Invoke job_worker._sweep_audio_deletions() out-of-process style (own pool)."""
    async def go():
        import database
        from utils.job_worker import _sweep_audio_deletions
        await database.create_pool()
        try:
            await _sweep_audio_deletions()
        finally:
            await database.close_pool()
    _run(go())


def backdate_grace(mid, minutes=30):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    db(lambda c: c.execute(
        "UPDATE meetings SET audio_grace_period_started_at=$1 WHERE id=$2", ts, mid))


def meeting_state(mid):
    async def go(c):
        m = await c.fetchrow(
            "SELECT status, audio_deletion_status, audio_deleted_at, audio_file_id FROM meetings WHERE id=$1", mid)
        a = await c.fetchrow(
            "SELECT is_deleted, deletion_status, storage_path FROM audio_files WHERE meeting_id=$1", mid)
        return dict(m) if m else None, (dict(a) if a else None)
    return db(go)


def content_fingerprint(payload: dict) -> dict:
    """Everything that constitutes the permanent record (must survive audio deletion)."""
    keys = ["transcript", "transcript_text", "analysis", "summary", "cqc_mappings",
            "care_cert_mappings", "custom_mappings", "actions", "risks", "speaker_text"]
    return {k: payload.get(k) for k in keys if k in payload}


# ── P1: sign-off → grace period → sweep → real storage delete ─────────────────
class TestP1AudioGdprLifecycle:
    def test_signoff_starts_grace_period_and_sweep_deletes_real_audio(self, admin_s, manager_s, jane_s, jane_id):
        m = create_meeting(admin_s, [jane_id], "p1_gdpr")
        mid, path = m["mid"], m["path"]
        try:
            assert storage_exists(path), "seeded audio not in Supabase"

            # snapshot the permanent record BEFORE any deletion
            before = admin_s.get(f"{BASE}/meetings/{mid}", timeout=90)
            assert before.status_code == 200, before.text[:300]
            before_json = before.json()
            fp_before = content_fingerprint(before_json)
            tr_before = admin_s.get(f"{BASE}/meetings/{mid}/transcript-text", timeout=90)
            db_before = db(lambda c: c.fetchrow(
                "SELECT t.text AS ttext, a.summary, a.cqc_mappings FROM transcripts t, analyses a "
                "WHERE t.meeting_id=$1 AND a.meeting_id=$1", mid))

            # all attendees mark reviewed
            r = jane_s.post(f"{BASE}/review/{mid}/mark-reviewed", timeout=90)
            assert r.status_code == 200, f"jane mark-reviewed {r.status_code}: {r.text[:300]}"
            attendees = db(lambda c: c.fetchval("SELECT attendees FROM meetings WHERE id=$1", mid))
            unreviewed = [a for a in json.loads(attendees) if not a.get("reviewed")]
            for a in unreviewed:
                # any other attendee (e.g. the admin creator) marks reviewed too
                db(lambda c: c.execute(
                    "UPDATE meetings SET attendees=$1::jsonb, status='reviewed' WHERE id=$2",
                    json.dumps([{**x, "reviewed": True} for x in json.loads(attendees)]), mid))
                break
            status = db(lambda c: c.fetchval("SELECT status FROM meetings WHERE id=$1", mid))
            assert status == "reviewed", f"expected all-reviewed status, got {status}"

            # manager signs off
            r = manager_s.post(f"{BASE}/review/{mid}/signoff", timeout=90)
            assert r.status_code == 200, f"signoff {r.status_code}: {r.text[:300]}"
            mrow, arow = meeting_state(mid)
            assert mrow["status"] == "signed_off"
            assert mrow["audio_deletion_status"] == "grace_period", mrow
            assert storage_exists(path), "audio deleted before grace period expired!"
            assert arow["is_deleted"] is False

            # grace period expired → recovery sweep
            backdate_grace(mid, 30)
            run_sweep()
            time.sleep(1)

            mrow, arow = meeting_state(mid)
            assert mrow["audio_deletion_status"] == "deleted", mrow
            assert mrow["audio_deleted_at"], mrow
            assert arow["is_deleted"] is True, arow
            assert arow["deletion_status"] == "deleted", arow
            # (a) file ACTUALLY gone from real Supabase Storage
            assert not storage_exists(path), "audio object STILL in Supabase Storage after sweep"

            # (d) transcript + analysis 100% unchanged
            after = admin_s.get(f"{BASE}/meetings/{mid}", timeout=90)
            assert after.status_code == 200, after.text[:300]
            fp_after = content_fingerprint(after.json())
            assert fp_after == fp_before, "permanent record changed by audio deletion!"
            tr_after = admin_s.get(f"{BASE}/meetings/{mid}/transcript-text", timeout=90)
            assert tr_after.status_code == tr_before.status_code
            assert tr_after.json() == tr_before.json(), "transcript text changed"
            db_after = db(lambda c: c.fetchrow(
                "SELECT t.text AS ttext, a.summary, a.cqc_mappings FROM transcripts t, analyses a "
                "WHERE t.meeting_id=$1 AND a.meeting_id=$1", mid))
            assert dict(db_after) == dict(db_before), "transcript/analysis rows mutated"
            assert db_after["ttext"] == TRANSCRIPT_TEXT
            assert db_after["summary"] == SUMMARY_TEXT

            # review endpoint still serves the record
            rv = manager_s.get(f"{BASE}/review/{mid}", timeout=90)
            assert rv.status_code == 200, rv.text[:300]
        finally:
            cleanup_meeting(m)

    def test_grace_period_background_task_path_deletes_real_audio(self, admin_s, manager_s, jane_s, jane_id):
        """Exercises review.delete_audio_after_grace() itself (the primary path,
        with its 300 s sleep patched out) rather than the recovery sweep."""
        m = create_meeting(admin_s, [jane_id], "p1_task")
        mid, path = m["mid"], m["path"]
        try:
            jane_s.post(f"{BASE}/review/{mid}/mark-reviewed", timeout=90)
            db(lambda c: c.execute("UPDATE meetings SET status='reviewed' WHERE id=$1", mid))
            assert manager_s.post(f"{BASE}/review/{mid}/signoff", timeout=90).status_code == 200
            tr_before = db(lambda c: c.fetchval("SELECT text FROM transcripts WHERE meeting_id=$1", mid))

            async def go():
                import database
                from routers import review as review_mod
                real_sleep = asyncio.sleep

                async def no_sleep(secs, *a, **k):
                    return await real_sleep(0)

                review_mod.asyncio.sleep = no_sleep
                await database.create_pool()
                try:
                    await review_mod.delete_audio_after_grace(mid)
                finally:
                    review_mod.asyncio.sleep = real_sleep
                    await database.close_pool()
            _run(go())

            mrow, arow = meeting_state(mid)
            assert mrow["audio_deletion_status"] == "deleted", mrow
            assert arow["is_deleted"] is True and arow["deletion_status"] == "deleted", arow
            assert not storage_exists(path), "audio still in storage after grace task"
            assert db(lambda c: c.fetchval(
                "SELECT text FROM transcripts WHERE meeting_id=$1", mid)) == tr_before
            assert db(lambda c: c.fetchval(
                "SELECT summary FROM analyses WHERE meeting_id=$1", mid)) == SUMMARY_TEXT
        finally:
            cleanup_meeting(m)

    def test_sweep_is_idempotent_and_ignores_non_expired(self, admin_s, manager_s, jane_s, jane_id):
        m = create_meeting(admin_s, [jane_id], "p1_idem")
        mid, path = m["mid"], m["path"]
        try:
            jane_s.post(f"{BASE}/review/{mid}/mark-reviewed", timeout=90)
            db(lambda c: c.execute("UPDATE meetings SET status='reviewed' WHERE id=$1", mid))
            r = manager_s.post(f"{BASE}/review/{mid}/signoff", timeout=90)
            assert r.status_code == 200, r.text[:300]
            # grace period still running → sweep must not touch it
            run_sweep()
            mrow, arow = meeting_state(mid)
            assert mrow["audio_deletion_status"] == "grace_period", mrow
            assert storage_exists(path)
            # expire + sweep twice
            backdate_grace(mid, 30)
            run_sweep()
            run_sweep()
            mrow, arow = meeting_state(mid)
            assert mrow["audio_deletion_status"] == "deleted"
            assert not storage_exists(path)
        finally:
            cleanup_meeting(m)


# ── P2: meeting deletion purges audio ─────────────────────────────────────────
class TestP2MeetingDeletion:
    def test_delete_meeting_removes_audio_from_storage(self, admin_s, jane_id):
        m = create_meeting(admin_s, [jane_id], "p2_del")
        mid, path = m["mid"], m["path"]
        try:
            assert storage_exists(path)
            r = admin_s.delete(f"{BASE}/meetings/{mid}", timeout=90)
            assert r.status_code == 200, f"delete meeting {r.status_code}: {r.text[:300]}"
            time.sleep(1)
            assert not storage_exists(path), "audio object still in storage after meeting delete"
            counts = db(lambda c: c.fetchrow(
                """SELECT (SELECT count(*) FROM meetings WHERE id=$1) m,
                          (SELECT count(*) FROM audio_files WHERE meeting_id=$1) a,
                          (SELECT count(*) FROM transcripts WHERE meeting_id=$1) t,
                          (SELECT count(*) FROM analyses WHERE meeting_id=$1) an,
                          (SELECT count(*) FROM evidence_feedback WHERE meeting_id=$1) ef""", mid))
            assert dict(counts) == {"m": 0, "a": 0, "t": 0, "an": 0, "ef": 0}, dict(counts)
        finally:
            remove_real_audio(path)
            db(lambda c: c.execute("DELETE FROM meetings WHERE id=$1", mid))

    def test_delete_meeting_whose_audio_already_purged(self, admin_s, manager_s, jane_s, jane_id):
        m = create_meeting(admin_s, [jane_id], "p2_already")
        mid, path = m["mid"], m["path"]
        try:
            jane_s.post(f"{BASE}/review/{mid}/mark-reviewed", timeout=90)
            db(lambda c: c.execute("UPDATE meetings SET status='reviewed' WHERE id=$1", mid))
            assert manager_s.post(f"{BASE}/review/{mid}/signoff", timeout=90).status_code == 200
            backdate_grace(mid, 30)
            run_sweep()
            assert not storage_exists(path)
            r = admin_s.delete(f"{BASE}/meetings/{mid}", timeout=90)
            assert r.status_code == 200, f"delete after purge {r.status_code}: {r.text[:300]}"
            assert db(lambda c: c.fetchval("SELECT count(*) FROM meetings WHERE id=$1", mid)) == 0
        finally:
            remove_real_audio(path)
            db(lambda c: c.execute("DELETE FROM meetings WHERE id=$1", mid))

    def test_delete_nonexistent_meeting_404(self, admin_s):
        r = admin_s.delete(f"{BASE}/meetings/{P}nope", timeout=90)
        assert r.status_code == 404, r.status_code


# ── P3: org deletion (customer offboarding) ───────────────────────────────────
class TestP3OrgDeletion:
    def test_org_delete_purges_everything_including_evidence_feedback_and_audio(self, super_s):
        r = super_s.post(f"{BASE}/super-admin/orgs",
                         json={"name": f"{P}throwaway_{uuid.uuid4().hex[:6]}", "jurisdiction": "england"},
                         timeout=90)
        assert r.status_code in (200, 201), f"create org {r.status_code}: {r.text[:300]}"
        oid = r.json()["id"]
        mid = f"{P}m_{uuid.uuid4().hex[:8]}"
        path = f"{P}storage/org_{mid}.webm"
        upload_real_audio(path)
        now = datetime.now(timezone.utc).isoformat()

        async def seed(c):
            await c.execute(
                "INSERT INTO meetings (id, org_id, title, status, created_at) VALUES ($1,$2,$3,'signed_off',$4)",
                mid, oid, f"{P}orgmeeting", now)
            await c.execute(
                """INSERT INTO audio_files (id, meeting_id, org_id, storage_path, is_deleted, deletion_status, created_at)
                   VALUES ($1,$2,$3,$4,FALSE,'not_started',$5)""",
                f"{P}af_{mid}", mid, oid, path, now)
            await c.execute(
                "INSERT INTO transcripts (id, meeting_id, org_id, text, created_at) VALUES ($1,$2,$3,$4,$5)",
                f"{P}tr_{mid}", mid, oid, "org transcript", now)
            await c.execute(
                "INSERT INTO analyses (id, meeting_id, org_id, summary, created_at) VALUES ($1,$2,$3,$4,$5)",
                f"{P}an_{mid}", mid, oid, "org summary", now)
            for action in ("accepted", "rejected"):
                await c.execute(
                    """INSERT INTO evidence_feedback (id, meeting_id, org_id, user_id, user_name,
                        evidence_item_id, evidence_type, standard_ref, manager_action, timestamp)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
                    f"{P}ef_{action}_{mid}", mid, oid, "u", "n", "ev1", "cqc", "R9", action, now)
            await c.execute(
                "INSERT INTO org_settings (id, org_id, name, created_at) VALUES ($1,$2,$3,$4)",
                f"{P}set_{mid}", oid, f"{P}branch", now)
            await c.execute(
                "INSERT INTO teams (id, org_id, setting_id, name, created_at) VALUES ($1,$2,$3,$4,$5)",
                f"{P}team_{mid}", oid, f"{P}set_{mid}", f"{P}team", now)
            await c.execute(
                "INSERT INTO focus_topics (id, org_id, text, created_at) VALUES ($1,$2,$3,$4)",
                f"{P}ft_{mid}", oid, f"{P}topic", now)
            await c.execute(
                "INSERT INTO standards_documents (id, org_id, filename, created_at) VALUES ($1,$2,$3,$4)",
                f"{P}sd_{mid}", oid, f"{P}doc.pdf", now)
        tables = {"meetings": "org_id", "audio_files": "org_id", "transcripts": "org_id",
                  "analyses": "org_id", "evidence_feedback": "org_id", "org_settings": "org_id",
                  "teams": "org_id", "focus_topics": "org_id", "standards_documents": "org_id",
                  "users": "org_id"}

        def counts():
            async def go(c):
                return {t: await c.fetchval(f"SELECT count(*) FROM {t} WHERE {col}=$1", oid)
                        for t, col in tables.items()}
            return db(go)

        pre = None
        try:
            db(seed)
            pre = counts()
            assert pre["evidence_feedback"] == 2, pre
            assert pre["meetings"] == 1 and pre["audio_files"] == 1, pre

            r = super_s.delete(f"{BASE}/super-admin/orgs/{oid}", timeout=120)
            assert r.status_code == 200, f"delete org {r.status_code}: {r.text[:300]}"
            time.sleep(1)
            post = counts()
            assert all(v == 0 for v in post.values()), f"residue after org delete: {post}"
            assert db(lambda c: c.fetchval("SELECT count(*) FROM organisations WHERE id=$1", oid)) == 0
            assert not storage_exists(path), "org audio object still in Supabase Storage"
        finally:
            remove_real_audio(path)
            db(lambda c: c.execute("DELETE FROM organisations WHERE id=$1", oid))


# ── P4: regression ────────────────────────────────────────────────────────────
class TestP4Regression:
    def test_report_transcript_evidence_and_bulk_accept(self, admin_s, manager_s, jane_id):
        m = create_meeting(admin_s, [jane_id], "p4_regr")
        mid = m["mid"]
        try:
            r = admin_s.get(f"{BASE}/meetings/{mid}", timeout=90)
            assert r.status_code == 200, r.text[:300]
            assert r.json().get("id") == mid
            r = admin_s.get(f"{BASE}/meetings/{mid}/transcript-text", timeout=90)
            assert r.status_code == 200, r.text[:300]
            r = manager_s.get(f"{BASE}/review/{mid}", timeout=90)
            assert r.status_code == 200, r.text[:300]

            before_ef = db(lambda c: c.fetchval(
                "SELECT count(*) FROM evidence_feedback WHERE meeting_id=$1", mid))
            r = manager_s.post(f"{BASE}/review/{mid}/evidence/bulk-action",
                               json={"confidence": "likely_evidence", "status": "accepted"}, timeout=90)
            assert r.status_code == 200, f"bulk-action {r.status_code}: {r.text[:300]}"
            assert r.json()["updated_count"] == 2, r.json()
            time.sleep(1)
            after_ef = db(lambda c: c.fetchval(
                "SELECT count(*) FROM evidence_feedback WHERE meeting_id=$1", mid))
            assert after_ef == before_ef + 2, (before_ef, after_ef)
            statuses = [x["status"] for x in json.loads(db(lambda c: c.fetchval(
                "SELECT cqc_mappings FROM analyses WHERE meeting_id=$1", mid)))]
            assert statuses == ["accepted", "accepted"], statuses
        finally:
            cleanup_meeting(m)

    def test_signoff_flow_for_meeting_without_audio(self, admin_s, manager_s, jane_s, jane_id):
        m = create_meeting(admin_s, [jane_id], "p4_noaudio", with_audio=False)
        mid = m["mid"]
        try:
            r = jane_s.post(f"{BASE}/review/{mid}/mark-reviewed", timeout=90)
            assert r.status_code == 200, r.text[:300]
            db(lambda c: c.execute("UPDATE meetings SET status='reviewed' WHERE id=$1", mid))
            r = manager_s.post(f"{BASE}/review/{mid}/signoff", timeout=90)
            assert r.status_code == 200, f"signoff no-audio {r.status_code}: {r.text[:300]}"
            mrow, arow = meeting_state(mid)
            assert mrow["audio_deletion_status"] == "grace_period", mrow
            assert arow is None
            backdate_grace(mid, 30)
            run_sweep()          # must not raise
            mrow, arow = meeting_state(mid)
            assert mrow["audio_deletion_status"] == "deleted", mrow
            # permanent record intact
            r = admin_s.get(f"{BASE}/meetings/{mid}", timeout=90)
            assert r.status_code == 200
            assert db(lambda c: c.fetchval(
                "SELECT text FROM transcripts WHERE meeting_id=$1", mid)) == TRANSCRIPT_TEXT
            # deleting a no-audio meeting also works
            assert admin_s.delete(f"{BASE}/meetings/{mid}", timeout=90).status_code == 200
        finally:
            db(lambda c: c.execute("DELETE FROM meetings WHERE id=$1", mid))


# ── P5: storage failure must be retryable ─────────────────────────────────────
class TestP5FailureSafety:
    def test_storage_delete_failure_leaves_row_in_grace_period(self, admin_s, manager_s, jane_s, jane_id):
        good = create_meeting(admin_s, [jane_id], "p5_good")
        bad = create_meeting(admin_s, [jane_id], "p5_bad")
        try:
            for m in (good, bad):
                jane_s.post(f"{BASE}/review/{m['mid']}/mark-reviewed", timeout=90)
                db(lambda c, mid=m["mid"]: c.execute(
                    "UPDATE meetings SET status='reviewed' WHERE id=$1", mid))
                assert manager_s.post(f"{BASE}/review/{m['mid']}/signoff", timeout=90).status_code == 200
                backdate_grace(m["mid"], 30)

            failing_path = bad["path"]

            async def go():
                import database
                from utils import job_worker
                original = job_worker.delete_audio

                async def flaky(path):
                    if path == failing_path:
                        raise RuntimeError("simulated storage failure")
                    return await original(path)

                job_worker.delete_audio = flaky
                await database.create_pool()
                try:
                    await job_worker._sweep_audio_deletions()
                finally:
                    job_worker.delete_audio = original
                    await database.close_pool()
            _run(go())

            # failing meeting: nothing marked deleted, file still present → retryable
            mrow, arow = meeting_state(bad["mid"])
            assert mrow["audio_deletion_status"] == "grace_period", mrow
            assert mrow["audio_deleted_at"] is None, mrow
            assert arow["is_deleted"] is False, arow
            assert arow["deletion_status"] != "deleted", arow
            assert storage_exists(bad["path"]), "file gone even though delete raised"

            # other meeting unaffected by the failure
            mrow2, arow2 = meeting_state(good["mid"])
            assert mrow2["audio_deletion_status"] == "deleted", mrow2
            assert not storage_exists(good["path"])

            # retry now succeeds
            run_sweep()
            mrow, arow = meeting_state(bad["mid"])
            assert mrow["audio_deletion_status"] == "deleted", mrow
            assert not storage_exists(bad["path"])
        finally:
            cleanup_meeting(good)
            cleanup_meeting(bad)


# ── residue audit ─────────────────────────────────────────────────────────────
class TestZResidue:
    def test_no_test_residue_left(self):
        async def go(c):
            out = {}
            out["meetings"] = await c.fetchval("SELECT count(*) FROM meetings WHERE title LIKE $1", f"{P}%")
            out["evidence_feedback"] = await c.fetchval(
                "SELECT count(*) FROM evidence_feedback WHERE id LIKE $1", f"{P}%")
            out["audio_files"] = await c.fetchval("SELECT count(*) FROM audio_files WHERE id LIKE $1", f"{P}%")
            out["orgs"] = await c.fetchval("SELECT count(*) FROM organisations WHERE name LIKE $1", f"{P}%")
            return out
        res = db(go)
        assert all(v == 0 for v in res.values()), f"residue: {res}"

    def test_no_storage_residue(self):
        h = {"Authorization": f"Bearer {SUPA_KEY}", "apikey": SUPA_KEY}
        r = requests.post(f"{SUPA_URL}/storage/v1/object/list/audio-recordings",
                          headers=h, json={"prefix": f"{P}storage/", "limit": 100}, timeout=60)
        assert r.status_code == 200, r.text[:200]
        names = [f["name"] for f in r.json()]
        assert names == [], f"storage residue: {names}"
