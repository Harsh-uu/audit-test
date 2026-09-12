"""
Iteration 128 — regression tests for Issue 3.3 (RLS drift fix, m020_disable_rls_drift).

Verifies (see review_request):
  1. Live DB state: 4 public.* tables have RLS disabled.
  2. schema_migrations ledger contains 020_disable_rls_drift (idempotent rerun).
  3. Auth flows (login for all 4 roles) still work — login_attempts read/write.
  4. Failed logins still write to login_attempts and lockout triggers.
  5. forgot-password writes to password_reset_tokens (accessed via with_admin()).
  6. Meeting deletion via /api/meetings/{id} deletes the associated jobs row.
  7. super_admin.delete_org reports jobs count in totals and removes the row.
"""
import asyncio
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import requests
from dotenv import dotenv_values

be_env = dotenv_values("/app/backend/.env")
fe_env = dotenv_values("/app/frontend/.env")
BASE = fe_env["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = be_env["DATABASE_URL"]

ADMIN = ("admin@supervision.com", "Admin123!")
MANAGER = ("manager@supervision.com", "Manager123!")
ATTENDEE = ("user@supervision.com", "AnotherNew789!")
SUPERADMIN = ("superadmin@1two.one", "NewPass123!")


# ───────── helpers ─────────
async def _connect():
    return await asyncpg.connect(DSN, ssl="require")


async def _force_mfa_code(email: str):
    conn = await _connect()
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email,
    )
    await conn.close()


async def _clear_lockouts():
    conn = await _connect()
    await conn.execute("DELETE FROM login_attempts")
    await conn.close()


def _login(email: str, password: str) -> requests.Session:
    # Best-effort clear rate-limit state so tests are deterministic
    asyncio.run(_clear_lockouts())
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=60)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_force_mfa_code(email))
        r2 = s.post(
            f"{BASE}/auth/verify-mfa",
            json={"mfa_session": data["mfa_session"], "code": "123456"},
            timeout=60,
        )
        assert r2.status_code == 200, f"mfa verify failed for {email}: {r2.text[:200]}"
    me = s.get(f"{BASE}/auth/me", timeout=30)
    assert me.status_code == 200, f"/auth/me failed for {email}"
    return s


# ────────── Tests ──────────

class TestRLSDBState:
    def test_four_public_tables_rls_disabled(self):
        async def run():
            conn = await _connect()
            rows = await conn.fetch(
                """SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                   FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE c.relkind='r' AND n.nspname='public' AND c.relname IN
                     ('jobs','login_attempts','password_reset_tokens','schema_migrations')
                   ORDER BY c.relname""",
            )
            await conn.close()
            return rows
        rows = asyncio.run(run())
        names = {r["relname"] for r in rows}
        assert names == {"jobs", "login_attempts", "password_reset_tokens", "schema_migrations"}, names
        for r in rows:
            assert r["relrowsecurity"] is False, f"public.{r['relname']} still has RLS enabled"
            assert r["relforcerowsecurity"] is False, f"public.{r['relname']} still has FORCE RLS"

    def test_migration_ledger_has_m020(self):
        async def run():
            conn = await _connect()
            rows = await conn.fetch("SELECT version FROM schema_migrations ORDER BY version")
            await conn.close()
            return rows
        versions = [r["version"] for r in asyncio.run(run())]
        assert "020_disable_rls_drift" in versions, versions
        assert len(versions) == 20, f"expected 20 migrations, got {len(versions)}: {versions}"

    def test_run_migrations_idempotent(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from migrations import run_migrations

        async def run():
            conn = await _connect()
            before = await conn.fetchval("SELECT COUNT(*) FROM schema_migrations")
            await run_migrations(conn)
            after = await conn.fetchval("SELECT COUNT(*) FROM schema_migrations")
            await conn.close()
            return before, after
        before, after = asyncio.run(run())
        assert before == after == 20


class TestAuthRegression:
    def test_admin_login(self):
        assert _login(*ADMIN).get(f"{BASE}/auth/me").json()["role"] == "admin"

    def test_manager_login(self):
        assert _login(*MANAGER).get(f"{BASE}/auth/me").json()["role"] == "manager"

    def test_attendee_login(self):
        assert _login(*ATTENDEE).get(f"{BASE}/auth/me").json()["role"] == "attendee"

    def test_superadmin_login(self):
        assert _login(*SUPERADMIN).get(f"{BASE}/auth/me").json()["role"] == "super_admin"


class TestLoginAttemptsWrites:
    """Failed logins must still write to login_attempts and lockout kicks in."""

    def test_failed_logins_write_rows_and_lockout_triggers(self):
        asyncio.run(_clear_lockouts())
        got_429 = False
        for _ in range(25):
            r = requests.post(
                f"{BASE}/auth/login",
                json={"email": ATTENDEE[0], "password": "definitely-wrong-pw"},
                timeout=30,
            )
            if r.status_code == 429:
                got_429 = True
                break
            assert r.status_code == 401, f"unexpected {r.status_code} {r.text[:200]}"

        async def count_rows():
            conn = await _connect()
            n = await conn.fetchval("SELECT COUNT(*) FROM login_attempts")
            await conn.close()
            return n
        n = asyncio.run(count_rows())
        assert n >= 1, "no rows written to login_attempts on failed logins"
        assert got_429, "lockout never triggered after 25 wrong passwords"
        asyncio.run(_clear_lockouts())


class TestPasswordResetTokens:
    """forgot-password (with_admin) must insert into password_reset_tokens (email column)."""

    def test_forgot_password_creates_token_row(self):
        email = ATTENDEE[0]

        async def cleanup_and_count_before():
            conn = await _connect()
            await conn.execute("DELETE FROM password_reset_tokens WHERE email=$1", email)
            await conn.execute("DELETE FROM login_attempts WHERE identifier LIKE 'fp_%'")
            n = await conn.fetchval(
                "SELECT COUNT(*) FROM password_reset_tokens WHERE email=$1", email
            )
            await conn.close()
            return n
        assert asyncio.run(cleanup_and_count_before()) == 0

        r = requests.post(f"{BASE}/auth/forgot-password", json={"email": email}, timeout=30)
        assert r.status_code == 200, f"forgot-password failed: {r.status_code} {r.text[:200]}"

        async def count_after():
            conn = await _connect()
            n = await conn.fetchval(
                "SELECT COUNT(*) FROM password_reset_tokens WHERE email=$1", email
            )
            await conn.close()
            return n
        assert asyncio.run(count_after()) >= 1, "no password_reset_tokens row inserted"


class TestJobsCascade:
    """The main functional fix — meeting deletion must delete jobs rows (was silent no-op pre-fix)."""

    async def _seed_meeting_and_job(self, admin_email=ADMIN[0]):
        conn = await _connect()
        u = await conn.fetchrow("SELECT id, org_id FROM users WHERE email=$1", admin_email)
        meeting_id = uuid.uuid4()
        job_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        # meetings.date is TIMESTAMP WITHOUT TIME ZONE — pass a naive datetime.
        naive_date = now.replace(tzinfo=None)
        await conn.execute(
            """INSERT INTO meetings (id, org_id, title, date, meeting_type,
               created_by, created_by_name, attendees, status, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$10)""",
            meeting_id, u["org_id"], "TEST_rls_drift", naive_date,
            "supervision", u["id"], "Test Admin", "[]", "draft", now,
        )
        await conn.execute(
            """INSERT INTO jobs (id, meeting_id, status, attempts, created_at, updated_at)
               VALUES ($1,$2,$3,0,$4,$4)""",
            job_id, meeting_id, "queued", now,
        )
        await conn.close()
        return meeting_id, job_id

    async def _job_exists(self, job_id):
        conn = await _connect()
        n = await conn.fetchval("SELECT COUNT(*) FROM jobs WHERE id=$1", job_id)
        await conn.close()
        return n

    def test_delete_meeting_removes_jobs_row(self):
        meeting_id, job_id = asyncio.run(self._seed_meeting_and_job())
        assert asyncio.run(self._job_exists(job_id)) == 1

        s = _login(*ADMIN)
        r = s.delete(f"{BASE}/meetings/{meeting_id}", timeout=30)
        assert r.status_code == 200, f"delete failed: {r.status_code} {r.text[:200]}"
        assert asyncio.run(self._job_exists(job_id)) == 0, "jobs row not deleted"

    def test_super_admin_delete_org_reports_jobs_deleted(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from routers.auth import hash_password

        async def seed():
            conn = await _connect()
            org_id = uuid.uuid4()
            user_id = uuid.uuid4()
            meeting_id = uuid.uuid4()
            job_id = uuid.uuid4()
            now = datetime.now(timezone.utc)
            naive_date = now.replace(tzinfo=None)
            suffix = secrets.token_hex(4)
            await conn.execute(
                "INSERT INTO organisations (id, name, slug, status, branding, created_at) VALUES ($1,$2,$3,'active','{}',$4)",
                org_id, f"TEST_rls_org_{suffix}", f"test-rls-org-{suffix}", now,
            )
            await conn.execute(
                """INSERT INTO users (id, email, password_hash, name, role, org_id, is_active, created_at)
                   VALUES ($1,$2,$3,'Test','admin',$4,TRUE,$5)""",
                user_id, f"test_rls_{suffix}@example.com",
                await hash_password("Whatever123!"), org_id, now,
            )
            await conn.execute(
                """INSERT INTO meetings (id, org_id, title, date, meeting_type,
                   created_by, created_by_name, attendees, status, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,'supervision',$5,'Test','[]'::jsonb,'draft',$6,$6)""",
                meeting_id, org_id, "TEST_meeting", naive_date, user_id, now,
            )
            await conn.execute(
                """INSERT INTO jobs (id, meeting_id, status, attempts, created_at, updated_at)
                   VALUES ($1,$2,'queued',0,$3,$3)""",
                job_id, meeting_id, now,
            )
            await conn.close()
            return org_id, job_id

        org_id, job_id = asyncio.run(seed())

        s = _login(*SUPERADMIN)
        r = s.delete(f"{BASE}/super-admin/orgs/{org_id}", timeout=60)
        assert r.status_code == 200, f"delete org failed: {r.status_code} {r.text[:200]}"
        body = r.json()
        assert "deleted" in body, body
        assert body["deleted"].get("jobs", 0) >= 1, f"expected jobs>=1 in totals, got {body['deleted']}"

        async def check():
            conn = await _connect()
            n = await conn.fetchval("SELECT COUNT(*) FROM jobs WHERE id=$1", job_id)
            await conn.close()
            return n
        assert asyncio.run(check()) == 0


class TestGeneralSmoke:
    def test_admin_list_meetings(self):
        s = _login(*ADMIN)
        r = s.get(f"{BASE}/meetings/", timeout=30)
        assert r.status_code == 200

    def test_super_admin_list_orgs(self):
        s = _login(*SUPERADMIN)
        r = s.get(f"{BASE}/super-admin/orgs", timeout=30)
        assert r.status_code == 200
