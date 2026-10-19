"""Backend regression tests for Deactivate + Hard Delete flow (Jan 2026)."""
import os
import sys
import uuid
import pytest
import requests
from dotenv import load_dotenv

# Load backend .env so we can spin up asyncpg pools directly for DB overrides (MFA seed, must_change_password clear).
load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://supervision-preview.preview.emergentagent.com").rstrip("/")

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PW = "Admin123!X"
MANAGER_EMAIL = "manager@supervision.com"
MANAGER_PW = "Manager123!"


def _db_execute(query: str, *args):
    """Run a one-shot SQL statement using a fresh asyncpg connection (no shared pool → no cross-loop bugs)."""
    import asyncio
    import asyncpg
    dsn = os.environ.get("DATABASE_URL") or os.environ["APP_DATABASE_URL"]
    async def _run():
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(query, *args)
        finally:
            await conn.close()
    asyncio.run(_run())


def _db_fetchval(query: str, *args):
    import asyncio
    import asyncpg
    dsn = os.environ.get("DATABASE_URL") or os.environ["APP_DATABASE_URL"]
    async def _run():
        conn = await asyncpg.connect(dsn)
        try:
            return await conn.fetchval(query, *args)
        finally:
            await conn.close()
    return asyncio.run(_run())



# ── Auth helpers ──────────────────────────────────────────────────────────
def _login_full(session: requests.Session, email: str, pw: str) -> bool:
    """Login + MFA bypass (for admin/manager which require MFA). Returns True on success."""
    r = session.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw})
    if r.status_code != 200:
        return False
    data = r.json()
    if not data.get("requires_mfa"):
        return True
    # MFA required - use DB direct override to bypass
    mfa_session = data.get("mfa_session")
    from routers.auth import _pw_ctx  # noqa: F401 - just to ensure module import
    import bcrypt as _bcrypt
    from datetime import datetime, timezone, timedelta
    h = _bcrypt.hashpw(b"123456", _bcrypt.gensalt()).decode()
    _db_execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, datetime.now(timezone.utc) + timedelta(minutes=10), email,
    )
    r2 = session.post(
        f"{BASE_URL}/api/auth/verify-mfa",
        json={"mfa_session": mfa_session, "code": "123456"},
    )
    return r2.status_code == 200


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    if not _login_full(s, ADMIN_EMAIL, ADMIN_PW):
        pytest.skip("Admin login failed")
    return s


@pytest.fixture(scope="module")
def manager_session():
    s = requests.Session()
    if not _login_full(s, MANAGER_EMAIL, MANAGER_PW):
        pytest.skip("Manager login failed")
    return s


# ── Test-user setup: create a fresh throwaway user via admin, complete their password ──

def _create_throwaway_user(admin_session):
    """Create an attendee via admin API, mark must_change_password=FALSE and set password so they can log in."""
    email = f"testdeact_{uuid.uuid4().hex[:8]}@example.com"
    name = f"TestDeact {uuid.uuid4().hex[:4]}"
    pw = "TestUser123!"
    r = admin_session.post(
        f"{BASE_URL}/api/admin/users",
        json={"email": email, "name": name, "role": "attendee", "password": pw},
    )
    assert r.status_code == 200, f"Create user failed: {r.status_code} {r.text}"
    user_id = r.json()["id"]

    # Clear must_change_password so login isn't forced into set-password mode AND
    # so DELETE /admin/users deactivates (not hard-deletes) this user.
    _db_execute("UPDATE users SET must_change_password=FALSE WHERE id=$1::uuid", user_id)
    _flag = _db_fetchval("SELECT must_change_password FROM users WHERE id=$1::uuid", user_id)
    assert _flag is False, f"must_change_password flip failed: still {_flag}"
    return {"id": user_id, "email": email, "name": name, "password": pw}


# ── Tests ─────────────────────────────────────────────────────────────────

class TestDeactivateAndHardDelete:

    def test_01_hard_delete_active_user_blocked_with_400(self, admin_session):
        """Backend guard: hard-delete on an ACTIVE user must return 400."""
        user = _create_throwaway_user(admin_session)
        r = admin_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}/hard-delete")
        assert r.status_code == 400, f"Expected 400 got {r.status_code}: {r.text}"
        detail = r.json().get("detail", "")
        assert "deactivate" in detail.lower(), f"Detail missing 'deactivate' guidance: {detail}"

        # Cleanup: deactivate then hard-delete
        admin_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}")
        admin_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}/hard-delete")

    def test_02_deactivate_then_login_returns_401(self, admin_session):
        """Deactivated user attempting login with correct password must get 401 with deactivated message."""
        user = _create_throwaway_user(admin_session)
        # Verify they can log in before deactivation
        s = requests.Session()
        r = s.post(f"{BASE_URL}/api/auth/login", json={"email": user["email"], "password": user["password"]})
        assert r.status_code == 200, f"Pre-deactivation login should succeed: {r.status_code} {r.text}"

        # Deactivate
        rd = admin_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}")
        assert rd.status_code == 200

        # Now login should 401 with deactivation message
        s2 = requests.Session()
        r2 = s2.post(f"{BASE_URL}/api/auth/login", json={"email": user["email"], "password": user["password"]})
        assert r2.status_code == 401, f"Deactivated login should 401: {r2.status_code} {r2.text}"
        detail = r2.json().get("detail", "")
        assert "deactivated" in detail.lower(), f"Missing 'deactivated' in detail: {detail}"

        # Cleanup
        admin_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}/hard-delete")

    def test_03_hard_delete_deactivated_user_succeeds(self, admin_session):
        """Full flow: create → deactivate → hard-delete → verify gone."""
        user = _create_throwaway_user(admin_session)
        # Deactivate
        rd = admin_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}")
        assert rd.status_code == 200

        # Verify still in list (deactivated but present)
        r_list = admin_session.get(f"{BASE_URL}/api/admin/users")
        assert r_list.status_code == 200
        found = [u for u in r_list.json() if u["id"] == user["id"]]
        assert len(found) == 1, "Deactivated user should still appear in /admin/users list"
        assert found[0]["is_active"] is False, "User should be marked inactive"

        # Hard delete
        rh = admin_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}/hard-delete")
        assert rh.status_code == 200, f"Hard delete failed: {rh.status_code} {rh.text}"
        assert "meetings_deleted" in rh.json()

        # Verify fully gone
        r_list2 = admin_session.get(f"{BASE_URL}/api/admin/users")
        gone = [u for u in r_list2.json() if u["id"] == user["id"]]
        assert len(gone) == 0, "User should be fully removed after hard-delete"

    def test_04_manager_cannot_hard_delete(self, admin_session, manager_session):
        """Manager (non-admin) must not be able to call hard-delete (403)."""
        user = _create_throwaway_user(admin_session)
        admin_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}")  # deactivate first

        r = manager_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}/hard-delete")
        assert r.status_code == 403, f"Manager hard-delete should be 403: {r.status_code} {r.text}"

        # Cleanup
        admin_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}/hard-delete")

    def test_05_manager_cannot_hard_delete_self(self, manager_session):
        """Manager calling hard-delete on any user - blocked by role check (403). Included for completeness."""
        # Get manager's own id
        r_me = manager_session.get(f"{BASE_URL}/api/auth/me")
        assert r_me.status_code == 200
        mgr_id = r_me.json()["id"]
        r = manager_session.delete(f"{BASE_URL}/api/admin/users/{mgr_id}/hard-delete")
        assert r.status_code == 403

    def test_06_admin_hard_delete_self_blocked_400(self, admin_session):
        """Admin hard-deleting their own account is blocked with 400."""
        r_me = admin_session.get(f"{BASE_URL}/api/auth/me")
        assert r_me.status_code == 200
        admin_id = r_me.json()["id"]
        r = admin_session.delete(f"{BASE_URL}/api/admin/users/{admin_id}/hard-delete")
        assert r.status_code == 400

    def test_07_manager_deactivate_self_blocked_400(self, manager_session):
        """Manager cannot deactivate self (400)."""
        r_me = manager_session.get(f"{BASE_URL}/api/auth/me")
        assert r_me.status_code == 200
        mgr_id = r_me.json()["id"]
        r = manager_session.delete(f"{BASE_URL}/api/admin/users/{mgr_id}")
        assert r.status_code == 400

    def test_08_manager_deactivate_admin_blocked_403(self, manager_session, admin_session):
        """Manager cannot deactivate an admin (403)."""
        r_me = admin_session.get(f"{BASE_URL}/api/auth/me")
        admin_id = r_me.json()["id"]
        r = manager_session.delete(f"{BASE_URL}/api/admin/users/{admin_id}")
        assert r.status_code == 403

    def test_09_reactivate_via_edit(self, admin_session):
        """Admin can reactivate a deactivated user via PUT /admin/users/{id} with is_active=true, then login works."""
        user = _create_throwaway_user(admin_session)
        # Deactivate
        admin_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}")
        # Reactivate
        rp = admin_session.put(f"{BASE_URL}/api/admin/users/{user['id']}", json={"is_active": True})
        assert rp.status_code == 200, f"Reactivate failed: {rp.status_code} {rp.text}"

        # Verify login now succeeds
        s = requests.Session()
        rl = s.post(f"{BASE_URL}/api/auth/login", json={"email": user["email"], "password": user["password"]})
        assert rl.status_code == 200, f"Post-reactivate login should succeed: {rl.status_code} {rl.text}"

        # Cleanup
        admin_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}")
        admin_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}/hard-delete")

    def test_10_hard_delete_nonexistent_user_404(self, admin_session):
        fake_id = str(uuid.uuid4())
        r = admin_session.delete(f"{BASE_URL}/api/admin/users/{fake_id}/hard-delete")
        assert r.status_code == 404

    def test_11_hard_delete_user_with_one_meeting_cascades(self, admin_session):
        """P0-03 regression: a user who is the attendee/subject of a meeting must
        have that meeting (and its cascaded rows) actually deleted, not silently
        skipped. Covers two compounding bugs that were fixed together:
        (1) the meeting lookup double-JSON-encoded its $1::jsonb parameter on the
        pooled connection, so `attendees @> $1::jsonb` never matched anything and
        meeting_ids was always empty; (2) the downstream DELETE statements cast
        meeting_ids to ::text[] against native `uuid` columns, which Postgres
        rejects outright — but was unreachable in practice because of bug (1)."""
        user = _create_throwaway_user(admin_session)

        meeting_id = str(uuid.uuid4())
        admin_id = _db_fetchval("SELECT id FROM users WHERE email=$1", ADMIN_EMAIL)
        org_id = _db_fetchval("SELECT org_id FROM users WHERE email=$1", ADMIN_EMAIL)
        attendees = [{"user_id": user["id"], "role": "attendee", "name": user["name"]}]
        _db_execute(
            "INSERT INTO meetings (id, org_id, title, status, attendees, created_by, created_at) "
            "VALUES ($1::uuid,$2::uuid,'P0-03 Regression Meeting','draft',$3::jsonb,$4::uuid, now())",
            meeting_id, str(org_id), __import__("json").dumps(attendees), str(admin_id),
        )
        # A cascaded row to prove the DELETE loop actually reaches dependent tables.
        _db_execute(
            "INSERT INTO transcripts (id, meeting_id, org_id, text, created_at) VALUES (gen_random_uuid(), $1::uuid, $2::uuid, 'repro transcript', now())",
            meeting_id, str(org_id),
        )

        # Deactivate then hard-delete
        rd = admin_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}")
        assert rd.status_code == 200
        rh = admin_session.delete(f"{BASE_URL}/api/admin/users/{user['id']}/hard-delete")
        assert rh.status_code == 200, f"Hard delete failed: {rh.status_code} {rh.text}"
        assert rh.json()["meetings_deleted"] == 1, f"Expected 1 meeting deleted, got: {rh.json()}"

        meeting_still_exists = _db_fetchval("SELECT id FROM meetings WHERE id=$1::uuid", meeting_id)
        assert meeting_still_exists is None, "Meeting must be gone after hard-delete"
        transcript_still_exists = _db_fetchval("SELECT id FROM transcripts WHERE meeting_id=$1::uuid", meeting_id)
        assert transcript_still_exists is None, "Cascaded transcript row must be gone after hard-delete"
