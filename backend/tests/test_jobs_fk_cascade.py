"""Iteration 121 — jobs.meeting_id FK cascade regression tests (migration m014).

Verifies:
1. Migration 014 recorded, FK fk_jobs_meeting_id exists with ON DELETE CASCADE,
   idx_jobs_meeting_id index exists, 0 orphan jobs rows.
2. DELETE /api/meetings/{id} cascades jobs rows.
3. Direct DB DELETE on a meeting cascades the jobs row via the FK constraint alone
   (proves the FK works, not just the manual cascade list).
4. 403 for manager attempting to delete meeting.
5. 404 for already-deleted meeting.
6. Regression: creating/updating jobs rows for an existing meeting still works
   (job_worker.py's insert path is not broken by the new FK).
7. DELETE /api/super-admin/orgs/{org_id} cascades jobs for meetings in that org
   (via a throwaway org — never touches Test Company).
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

_be = dotenv_values("/app/backend/.env")
_fe = dotenv_values("/app/frontend/.env")
BASE = _fe["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = _be["DATABASE_URL"]

TEST_COMPANY_ORG_ID = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"


# ── Helpers ────────────────────────────────────────────────────────────────
def _login(email: str, password: str) -> requests.Session:
    """Login via API; if MFA required, force code to bcrypt('123456') and verify."""
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    data = r.json()
    if data.get("requires_mfa"):
        async def _override():
            conn = await asyncpg.connect(DSN, ssl="require")
            h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
            exp = datetime.now(timezone.utc) + timedelta(minutes=10)
            await conn.execute(
                "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
                h, exp, email,
            )
            await conn.close()
        asyncio.run(_override())
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=30)
        assert r2.status_code == 200, f"mfa verify failed: {r2.status_code} {r2.text[:200]}"
    return s


async def _db():
    return await asyncpg.connect(DSN, ssl="require")


@pytest.fixture(scope="module")
def admin_session():
    return _login("admin@supervision.com", "Admin123!")


@pytest.fixture(scope="module")
def manager_session():
    return _login("manager@supervision.com", "Manager123!")


@pytest.fixture(scope="module")
def super_admin_session():
    return _login("superadmin@1two.one", "NewPass123!")


# ── 1. DB-level verification ───────────────────────────────────────────────
def test_migration_014_recorded():
    async def _run():
        conn = await _db()
        try:
            row = await conn.fetchrow(
                "SELECT version FROM schema_migrations WHERE version=$1",
                "014_jobs_fk_cascade",
            )
            assert row is not None, "migration 014_jobs_fk_cascade not recorded in schema_migrations"
        finally:
            await conn.close()
    asyncio.run(_run())


def test_fk_constraint_exists_with_cascade():
    async def _run():
        conn = await _db()
        try:
            row = await conn.fetchrow(
                """SELECT confdeltype FROM pg_constraint
                   WHERE conname='fk_jobs_meeting_id' AND contype='f'"""
            )
            assert row is not None, "fk_jobs_meeting_id constraint not found on jobs table"
            # 'c' == CASCADE (see pg docs on pg_constraint.confdeltype).
            # asyncpg returns "char" pg type as bytes, hence the b'c' compare.
            cdt = row["confdeltype"]
            if isinstance(cdt, bytes):
                cdt = cdt.decode()
            assert cdt == "c", f"expected CASCADE on delete, got {cdt!r}"
        finally:
            await conn.close()
    asyncio.run(_run())


def test_idx_jobs_meeting_id_exists():
    async def _run():
        conn = await _db()
        try:
            row = await conn.fetchrow(
                "SELECT indexname FROM pg_indexes WHERE indexname='idx_jobs_meeting_id' AND tablename='jobs'"
            )
            assert row is not None, "idx_jobs_meeting_id index not found on jobs table"
        finally:
            await conn.close()
    asyncio.run(_run())


def test_no_orphan_jobs_rows():
    async def _run():
        conn = await _db()
        try:
            row = await conn.fetchrow(
                """SELECT count(*) c FROM jobs
                   WHERE meeting_id IS NOT NULL
                     AND NOT EXISTS (SELECT 1 FROM meetings m WHERE m.id = jobs.meeting_id)"""
            )
            assert row["c"] == 0, f"found {row['c']} orphan jobs rows"
        finally:
            await conn.close()
    asyncio.run(_run())


# ── Helper to create/cleanup a meeting + job for cascade tests ─────────────
async def _insert_job(meeting_id: str) -> str:
    conn = await _db()
    try:
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        await conn.execute(
            """INSERT INTO jobs (id, meeting_id, audio_path, status, attempts, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$6)""",
            job_id, meeting_id, "test/path.mp3", "pending", 0, now,
        )
        return job_id
    finally:
        await conn.close()


async def _count_jobs(meeting_id: str) -> int:
    conn = await _db()
    try:
        row = await conn.fetchrow("SELECT count(*) c FROM jobs WHERE meeting_id=$1", meeting_id)
        return row["c"]
    finally:
        await conn.close()


def _create_meeting(session: requests.Session, title="TEST_cascade") -> str:
    r = session.post(f"{BASE}/meetings/", json={
        "title": title,
        "date": datetime.now(timezone.utc).isoformat(),
        "meeting_type": "supervision",
        "attendee_ids": [],
    }, timeout=30)
    assert r.status_code == 200, f"create meeting failed: {r.status_code} {r.text[:200]}"
    return r.json()["id"]


# ── 2. DELETE /api/meetings/{id} cascades jobs ─────────────────────────────
def test_delete_meeting_via_api_cascades_jobs(admin_session):
    meeting_id = _create_meeting(admin_session, "TEST_delete_cascade_api")
    asyncio.run(_insert_job(meeting_id))
    assert asyncio.run(_count_jobs(meeting_id)) == 1

    r = admin_session.delete(f"{BASE}/meetings/{meeting_id}", timeout=30)
    assert r.status_code == 200, f"delete failed: {r.status_code} {r.text[:200]}"

    # jobs row must be gone (via either manual cascade or FK, doesn't matter)
    assert asyncio.run(_count_jobs(meeting_id)) == 0


# ── 3. FK-only cascade: prove the constraint itself works ──────────────────
def test_fk_cascades_on_direct_db_delete(admin_session):
    meeting_id = _create_meeting(admin_session, "TEST_fk_only_cascade")
    asyncio.run(_insert_job(meeting_id))
    assert asyncio.run(_count_jobs(meeting_id)) == 1

    # Bypass the API's manual cascade — delete the meeting row directly. Only
    # the FK ON DELETE CASCADE should clean the jobs row here.
    async def _direct_delete():
        conn = await _db()
        try:
            # Also need to clean other FK-cascading tables that reference meetings
            await conn.execute("DELETE FROM meetings WHERE id=$1", meeting_id)
        finally:
            await conn.close()
    asyncio.run(_direct_delete())

    assert asyncio.run(_count_jobs(meeting_id)) == 0, "FK ON DELETE CASCADE did not remove jobs row"


# ── 4. 403 for non-admin ───────────────────────────────────────────────────
def test_manager_cannot_delete_meeting(admin_session, manager_session):
    meeting_id = _create_meeting(admin_session, "TEST_403_manager_delete")
    try:
        r = manager_session.delete(f"{BASE}/meetings/{meeting_id}", timeout=30)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"
    finally:
        admin_session.delete(f"{BASE}/meetings/{meeting_id}", timeout=30)


# ── 5. 404 for already-deleted meeting ─────────────────────────────────────
def test_delete_already_deleted_returns_404(admin_session):
    meeting_id = _create_meeting(admin_session, "TEST_404_double_delete")
    r1 = admin_session.delete(f"{BASE}/meetings/{meeting_id}", timeout=30)
    assert r1.status_code == 200
    r2 = admin_session.delete(f"{BASE}/meetings/{meeting_id}", timeout=30)
    assert r2.status_code == 404


# ── 6. Regression: job insert/update still works for live meetings ─────────
def test_job_insert_update_still_works_for_live_meeting(admin_session):
    """Simulates what job_worker.py does — insert a pending job, update to
    processing, then to completed. FK must not block any of these."""
    meeting_id = _create_meeting(admin_session, "TEST_regression_job_lifecycle")
    try:
        job_id = asyncio.run(_insert_job(meeting_id))

        async def _lifecycle():
            conn = await _db()
            try:
                await conn.execute(
                    "UPDATE jobs SET status=$1, attempts=attempts+1, updated_at=NOW() WHERE id=$2",
                    "processing", job_id,
                )
                await conn.execute(
                    "UPDATE jobs SET status=$1, updated_at=NOW() WHERE id=$2",
                    "completed", job_id,
                )
                row = await conn.fetchrow(
                    "SELECT status, attempts FROM jobs WHERE id=$1", job_id
                )
                return row
            finally:
                await conn.close()

        row = asyncio.run(_lifecycle())
        assert row["status"] == "completed"
        assert row["attempts"] >= 1  # our UPDATE ran; job_worker may also bump this
        # Meeting still exists — job history intact for a live meeting
        assert asyncio.run(_count_jobs(meeting_id)) == 1
    finally:
        admin_session.delete(f"{BASE}/meetings/{meeting_id}", timeout=30)


# ── 7. Super-admin org deletion cascades jobs ──────────────────────────────
def test_super_admin_org_delete_cascades_jobs(super_admin_session):
    """Create a throwaway org via super-admin API, insert a meeting + job in it
    directly via DB (super-admin has no per-org login), delete the org via API,
    then verify the job row cascaded away with the meeting."""
    unique = uuid.uuid4().hex[:8]
    r = super_admin_session.post(f"{BASE}/super-admin/orgs", json={
        "name": f"TEST_throwaway_{unique}",
        "jurisdiction": "england",
    }, timeout=30)
    assert r.status_code == 200, f"create org failed: {r.status_code} {r.text[:200]}"
    throwaway_org_id = r.json()["id"]
    assert throwaway_org_id != TEST_COMPANY_ORG_ID  # sanity: never the real org

    meeting_id = str(uuid.uuid4())

    async def _seed():
        conn = await _db()
        try:
            now = datetime.now(timezone.utc)
            await conn.execute(
                """INSERT INTO meetings (id, org_id, title, date, meeting_type, status, created_by, created_by_name, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9)""",
                meeting_id, throwaway_org_id, "TEST_super_admin_cascade",
                now.isoformat(), "supervision", "draft",
                str(uuid.uuid4()), "seed", now,
            )
            job_id = str(uuid.uuid4())
            await conn.execute(
                """INSERT INTO jobs (id, meeting_id, audio_path, status, attempts, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$6)""",
                job_id, meeting_id, "test/path.mp3", "pending", 0, now,
            )
            return job_id
        finally:
            await conn.close()

    job_id = asyncio.run(_seed())
    assert asyncio.run(_count_jobs(meeting_id)) == 1

    # Delete the org via API
    r = super_admin_session.delete(f"{BASE}/super-admin/orgs/{throwaway_org_id}", timeout=60)
    assert r.status_code == 200, f"delete org failed: {r.status_code} {r.text[:200]}"

    # Both meeting and job must be gone
    async def _check():
        conn = await _db()
        try:
            m = await conn.fetchrow("SELECT id FROM meetings WHERE id=$1", meeting_id)
            j = await conn.fetchrow("SELECT id FROM jobs WHERE id=$1", job_id)
            org = await conn.fetchrow("SELECT id FROM organisations WHERE id=$1", throwaway_org_id)
            return m, j, org
        finally:
            await conn.close()

    m, j, org = asyncio.run(_check())
    assert m is None, "meeting still exists after org delete"
    assert j is None, "jobs row still exists after org delete — cascade broken"
    assert org is None, "organisation still exists after delete"

    # Sanity: Test Company org is still intact
    async def _check_test_org_intact():
        conn = await _db()
        try:
            row = await conn.fetchrow("SELECT id FROM organisations WHERE id=$1", TEST_COMPANY_ORG_ID)
            return row
        finally:
            await conn.close()
    assert asyncio.run(_check_test_org_intact()) is not None, "TEST COMPANY ORG WAS DELETED — DISASTER"
