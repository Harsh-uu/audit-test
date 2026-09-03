"""Iteration 112 — Supabase Auth migration (Phases 1-4) regression suite.

Covers:
  * login: bcrypt fallback (supabase_password_set=FALSE) vs Supabase path (TRUE)
  * old-password invalidation for migrated users
  * MFA gate change: optional for admin/manager, mandatory for super_admin
  * toggle-mfa opt-in still gates login
  * user provisioning endpoints (admin/users, org/invite-user, super-admin org users)
  * token invite flow (super-admin invite -> GET invite -> accept-invite -> login)
  * forgot-password -> reset-password round trip; change-password flow
  * non-auth regression: dashboard / meetings / org / standards still work
"""
import asyncio
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

FE = dotenv_values("/app/frontend/.env")
BE = dotenv_values("/app/backend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or FE["REACT_APP_BACKEND_URL"]).rstrip("/")
DSN = BE["DATABASE_URL"]

CREDS_FILE = Path("/app/memory/test_credentials.md")

ADMIN = ("admin@supervision.com", "Admin123!")
MANAGER = ("manager@supervision.com", "Manager123!")
SUPERADMIN = ("superadmin@1two.one", "NewPass123!")
JANE = ("jane@supervision.com", "JaneNew456!")
STAFF = ("user@supervision.com", "AnotherNew789!")
STAFF_OLD_PASSWORD = "Staff123!"

TEST_ORG_ID = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"


# ── DB helpers ───────────────────────────────────────────────────────────────
def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _q(sql, *args, fetch="all"):
    conn = await asyncpg.connect(DSN)
    try:
        if fetch == "all":
            return [dict(r) for r in await conn.fetch(sql, *args)]
        if fetch == "row":
            r = await conn.fetchrow(sql, *args)
            return dict(r) if r else None
        return await conn.execute(sql, *args)
    finally:
        await conn.close()


def db_all(sql, *args):
    return _run(_q(sql, *args, fetch="all"))


def db_row(sql, *args):
    return _run(_q(sql, *args, fetch="row"))


def db_exec(sql, *args):
    return _run(_q(sql, *args, fetch="exec"))


def clear_rate_limits():
    db_exec("DELETE FROM login_attempts")


def set_mfa_code(email, code="123456"):
    h = bcrypt.hashpw(code.encode(), bcrypt.gensalt()).decode()
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    db_exec(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email,
    )


def delete_supabase_identity(user_id):
    try:
        import sys
        sys.path.insert(0, "/app/backend")
        os.environ.setdefault("SUPABASE_URL", BE["SUPABASE_URL"])
        os.environ.setdefault("SUPABASE_SERVICE_KEY", BE["SUPABASE_SERVICE_KEY"])
        from utils.supabase_auth import _get_admin_client
        _get_admin_client().auth.admin.delete_user(user_id)
    except Exception as exc:  # pragma: no cover - cleanup best effort
        print(f"[cleanup] supabase delete_user({user_id}) failed: {exc}")


def purge_user(email):
    row = db_row("SELECT id FROM users WHERE email=$1", email)
    if row:
        uid = str(row["id"])
        db_exec("DELETE FROM invitations WHERE user_id=$1", row["id"])
        db_exec("DELETE FROM password_reset_tokens WHERE email=$1", email)
        db_exec("DELETE FROM login_attempts WHERE identifier=$1", email)
        db_exec("DELETE FROM users WHERE id=$1", row["id"])
        delete_supabase_identity(uid)


# ── API helpers ──────────────────────────────────────────────────────────────
def login(email, password):
    return requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=45)


def login_cookies(email, password, mfa=False):
    r = login(email, password)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:300]}"
    body = r.json()
    if body.get("requires_mfa"):
        assert mfa, f"unexpected MFA requirement for {email}"
        set_mfa_code(email)
        r2 = requests.post(
            f"{BASE_URL}/api/auth/verify-mfa",
            json={"mfa_session": body["mfa_session"], "code": "123456"}, timeout=45,
        )
        assert r2.status_code == 200, f"verify-mfa failed: {r2.status_code} {r2.text[:300]}"
        return r2.cookies
    assert mfa is False
    return r.cookies


@pytest.fixture(scope="session", autouse=True)
def _rate_limit_reset():
    clear_rate_limits()
    yield
    clear_rate_limits()


@pytest.fixture(scope="session")
def admin_cookies():
    return login_cookies(*ADMIN)


@pytest.fixture(scope="session")
def manager_cookies():
    return login_cookies(*MANAGER)


@pytest.fixture(scope="session")
def superadmin_cookies():
    return login_cookies(*SUPERADMIN, mfa=True)


# ── test credentials sanity ──────────────────────────────────────────────────
class TestCredentialsFile:
    def test_credentials_file_present(self):
        assert CREDS_FILE.exists(), "/app/memory/test_credentials.md missing"
        content = CREDS_FILE.read_text()
        for email in (ADMIN[0], MANAGER[0], SUPERADMIN[0], JANE[0], STAFF[0]):
            assert email in content


# ── health ───────────────────────────────────────────────────────────────────
class TestHealth:
    def test_health(self):
        r = requests.get(f"{BASE_URL}/api/health", timeout=30)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


# ── migration flag state ─────────────────────────────────────────────────────
class TestMigrationFlags:
    def test_all_users_have_supabase_identity(self):
        rows = db_all("SELECT email, supabase_migrated, supabase_password_set FROM users")
        assert rows, "no users in DB"
        not_migrated = [r["email"] for r in rows if not r["supabase_migrated"]]
        assert not_migrated == [], f"users without Supabase identity: {not_migrated}"

    def test_flags_are_separate_columns(self):
        """supabase_migrated TRUE + supabase_password_set FALSE must be a real state."""
        rows = db_all(
            "SELECT email FROM users WHERE supabase_migrated=TRUE AND supabase_password_set=FALSE"
        )
        assert rows, "expected at least one identity-provisioned-but-not-password-set user"

    def test_expected_migrated_users(self):
        for email in (JANE[0], STAFF[0]):
            row = db_row("SELECT supabase_password_set FROM users WHERE email=$1", email)
            assert row and row["supabase_password_set"] is True, f"{email} not Supabase-backed"


# ── login paths ──────────────────────────────────────────────────────────────
class TestLoginPaths:
    def test_bcrypt_fallback_admin_login(self):
        """admin has supabase_password_set=FALSE -> bcrypt fallback must still work."""
        flag = db_row("SELECT supabase_password_set FROM users WHERE email=$1", ADMIN[0])
        assert flag["supabase_password_set"] is False, "precondition changed: admin now Supabase-backed"
        r = login(*ADMIN)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("requires_mfa") is None, f"admin should not require MFA: {body}"
        assert body["email"] == ADMIN[0]
        assert body["role"] == "admin"
        assert "supervision_access" in r.cookies

    def test_bcrypt_fallback_manager_login_no_mfa(self):
        r = login(*MANAGER)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("requires_mfa") is None, f"manager should not require MFA: {body}"
        assert body["role"] == "manager"

    def test_supabase_login_jane(self):
        r = login(*JANE)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["email"] == JANE[0]
        assert "supervision_access" in r.cookies

    def test_supabase_login_staff(self):
        r = login(*STAFF)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["role"] == "attendee"

    def test_old_password_rejected_for_migrated_user(self):
        r = login(STAFF[0], STAFF_OLD_PASSWORD)
        assert r.status_code == 401, f"old password still accepted: {r.status_code} {r.text[:200]}"
        assert "Invalid credentials" in r.json()["detail"]
        clear_rate_limits()

    def test_wrong_password_bcrypt_user(self):
        r = login(ADMIN[0], "TotallyWrong999!")
        assert r.status_code == 401
        assert "Invalid credentials" in r.json()["detail"]
        clear_rate_limits()

    def test_wrong_password_supabase_user(self):
        r = login(JANE[0], "TotallyWrong999!")
        assert r.status_code == 401
        assert "Invalid credentials" in r.json()["detail"]
        clear_rate_limits()

    def test_unknown_email_returns_401(self):
        r = login(f"nobody-{uuid.uuid4().hex[:8]}@example.com", "Whatever123!")
        assert r.status_code == 401
        clear_rate_limits()

    def test_lockout_after_five_failures(self):
        email = JANE[0]
        clear_rate_limits()
        codes = [login(email, "Nope12345!x").status_code for _ in range(5)]
        assert codes == [401] * 5, codes
        row = db_row("SELECT count FROM login_attempts WHERE identifier=$1", email)
        assert row and row["count"] >= 5, f"lockout counter not recorded: {row}"
        r = login(email, JANE[1])
        assert r.status_code == 429, f"expected lockout 429, got {r.status_code}"
        clear_rate_limits()
        r = login(email, JANE[1])
        assert r.status_code == 200, "correct password should work after lockout cleared"


# ── MFA behaviour ────────────────────────────────────────────────────────────
class TestMfaGate:
    def test_super_admin_still_requires_mfa(self):
        r = login(*SUPERADMIN)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("requires_mfa") is True, f"super_admin MFA no longer enforced: {body}"
        assert body.get("mfa_session")
        assert "supervision_access" not in r.cookies

    def test_super_admin_mfa_verify_end_to_end(self):
        r = login(*SUPERADMIN)
        body = r.json()
        assert body.get("requires_mfa") is True
        set_mfa_code(SUPERADMIN[0])
        r2 = requests.post(
            f"{BASE_URL}/api/auth/verify-mfa",
            json={"mfa_session": body["mfa_session"], "code": "123456"}, timeout=45,
        )
        assert r2.status_code == 200, r2.text[:300]
        assert r2.json()["role"] == "super_admin"
        assert "supervision_access" in r2.cookies
        me = requests.get(f"{BASE_URL}/api/auth/me", cookies=r2.cookies, timeout=30)
        assert me.status_code == 200
        assert me.json()["email"] == SUPERADMIN[0]

    def test_super_admin_wrong_mfa_code_rejected(self):
        r = login(*SUPERADMIN)
        body = r.json()
        set_mfa_code(SUPERADMIN[0])
        r2 = requests.post(
            f"{BASE_URL}/api/auth/verify-mfa",
            json={"mfa_session": body["mfa_session"], "code": "000000"}, timeout=45,
        )
        assert r2.status_code == 401
        assert "Invalid code" in r2.json()["detail"]
        db_exec("UPDATE users SET mfa_code_attempts=0 WHERE email=$1", SUPERADMIN[0])

    def test_admin_can_opt_into_mfa_and_login_gate_follows(self, admin_cookies):
        set_mfa_code(ADMIN[0])
        r = requests.post(f"{BASE_URL}/api/auth/toggle-mfa", cookies=admin_cookies,
                          json={"code": "123456", "enable": True}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["mfa_enabled"] is True
        try:
            flag = db_row("SELECT mfa_enabled FROM users WHERE email=$1", ADMIN[0])
            assert flag["mfa_enabled"] is True, "toggle-mfa did not enable MFA"
            lr = login(*ADMIN)
            assert lr.status_code == 200
            assert lr.json().get("requires_mfa") is True, "MFA opt-in not honoured at login"
            # complete MFA to prove flow works for admin too
            set_mfa_code(ADMIN[0])
            vr = requests.post(
                f"{BASE_URL}/api/auth/verify-mfa",
                json={"mfa_session": lr.json()["mfa_session"], "code": "123456"}, timeout=45,
            )
            assert vr.status_code == 200, vr.text[:300]
        finally:
            set_mfa_code(ADMIN[0])
            off = requests.post(f"{BASE_URL}/api/auth/toggle-mfa", cookies=admin_cookies,
                                json={"code": "123456", "enable": False}, timeout=30)
            if off.status_code != 200:
                db_exec("UPDATE users SET mfa_enabled=FALSE WHERE email=$1", ADMIN[0])
            assert off.status_code == 200, f"toggle-mfa disable failed: {off.text[:300]}"
        lr = login(*ADMIN)
        assert lr.status_code == 200
        assert lr.json().get("requires_mfa") is None, "MFA still required after opting out"


# ── user provisioning endpoints ──────────────────────────────────────────────
@pytest.fixture
def temp_emails():
    created = []
    yield created
    for email in created:
        purge_user(email)


class TestProvisioning:
    def test_admin_create_user_can_login_immediately(self, admin_cookies, temp_emails):
        email = f"test_iter112_admin_{uuid.uuid4().hex[:6]}@example.com"
        pwd = "CreatedPass123!"
        temp_emails.append(email)
        r = requests.post(f"{BASE_URL}/api/admin/users", cookies=admin_cookies, timeout=60,
                          json={"email": email, "name": "TEST Iter112", "role": "attendee", "password": pwd})
        assert r.status_code == 200, r.text[:300]
        assert r.json()["email"] == email
        row = db_row("SELECT supabase_migrated, supabase_password_set, must_change_password"
                     " FROM users WHERE email=$1", email)
        assert row["supabase_migrated"] is True
        assert row["supabase_password_set"] is True, "new user not provisioned in Supabase"
        assert row["must_change_password"] is True
        lr = login(email, pwd)
        assert lr.status_code == 200, f"new user cannot log in: {lr.text[:300]}"
        assert lr.json()["must_change_password"] is True

    def test_admin_create_user_duplicate_email_400(self, admin_cookies):
        r = requests.post(f"{BASE_URL}/api/admin/users", cookies=admin_cookies, timeout=60,
                          json={"email": ADMIN[0], "name": "dup", "role": "attendee",
                                "password": "CreatedPass123!"})
        assert r.status_code == 400
        assert "already exists" in r.json()["detail"].lower()

    def test_admin_create_user_requires_admin(self, manager_cookies):
        r = requests.post(f"{BASE_URL}/api/admin/users", cookies=manager_cookies, timeout=60,
                          json={"email": "test_iter112_forbidden@example.com", "name": "x",
                                "role": "attendee", "password": "CreatedPass123!"})
        assert r.status_code == 403

    def test_org_invite_user_can_login_immediately(self, manager_cookies, temp_emails):
        email = f"test_iter112_org_{uuid.uuid4().hex[:6]}@example.com"
        pwd = "OrgInvite123!"
        temp_emails.append(email)
        r = requests.post(f"{BASE_URL}/api/org/invite-user", cookies=manager_cookies, timeout=60,
                          json={"name": "TEST Iter112 Org", "email": email, "role": "attendee",
                                "password": pwd})
        assert r.status_code == 200, r.text[:300]
        row = db_row("SELECT supabase_password_set FROM users WHERE email=$1", email)
        assert row["supabase_password_set"] is True
        lr = login(email, pwd)
        assert lr.status_code == 200, lr.text[:300]

    def test_super_admin_create_org_user_can_login_immediately(self, superadmin_cookies, temp_emails):
        email = f"test_iter112_sa_{uuid.uuid4().hex[:6]}@example.com"
        pwd = "SaCreated123!"
        temp_emails.append(email)
        r = requests.post(f"{BASE_URL}/api/super-admin/orgs/{TEST_ORG_ID}/users",
                          cookies=superadmin_cookies, timeout=60,
                          json={"email": email, "name": "TEST Iter112 SA", "password": pwd,
                                "role": "manager"})
        assert r.status_code == 200, r.text[:300]
        row = db_row("SELECT supabase_password_set FROM users WHERE email=$1", email)
        assert row["supabase_password_set"] is True
        lr = login(email, pwd)
        assert lr.status_code == 200, lr.text[:300]
        assert lr.json().get("requires_mfa") is None, "new manager should not be forced into MFA"

    def test_super_admin_org_user_requires_super_admin(self, admin_cookies):
        r = requests.post(f"{BASE_URL}/api/super-admin/orgs/{TEST_ORG_ID}/users",
                          cookies=admin_cookies, timeout=60,
                          json={"email": "test_iter112_nope@example.com", "name": "x",
                                "password": "SaCreated123!", "role": "manager"})
        assert r.status_code == 403


class TestInviteTokenFlow:
    def test_invite_accept_and_login(self, superadmin_cookies, temp_emails):
        email = f"test_iter112_inv_{uuid.uuid4().hex[:6]}@example.com"
        temp_emails.append(email)
        r = requests.post(f"{BASE_URL}/api/super-admin/orgs/{TEST_ORG_ID}/invite",
                          cookies=superadmin_cookies, timeout=60,
                          json={"email": email, "name": "TEST Iter112 Invite"})
        assert r.status_code == 200, r.text[:300]
        row = db_row("SELECT u.id, u.is_active, u.supabase_migrated, u.supabase_password_set, i.token"
                     " FROM users u JOIN invitations i ON i.user_id = u.id WHERE u.email=$1", email)
        assert row, "invite row not created"
        assert row["supabase_migrated"] is True
        assert row["supabase_password_set"] is False, "invite should not set a password yet"
        token = row["token"]

        g = requests.get(f"{BASE_URL}/api/auth/invite/{token}", timeout=30)
        assert g.status_code == 200, g.text[:300]
        assert g.json()["email"] == email

        pwd = "InviteChosen123!"
        a = requests.post(f"{BASE_URL}/api/auth/accept-invite", timeout=60,
                          json={"token": token, "name": "TEST Iter112 Invite", "password": pwd})
        assert a.status_code == 200, a.text[:300]
        row2 = db_row("SELECT supabase_password_set, must_change_password FROM users WHERE email=$1", email)
        assert row2["supabase_password_set"] is True, "accept-invite did not set Supabase password"
        assert row2["must_change_password"] is False

        lr = login(email, pwd)
        assert lr.status_code == 200, f"invited admin cannot log in: {lr.text[:300]}"
        assert lr.json()["role"] == "admin"

        reused = requests.post(f"{BASE_URL}/api/auth/accept-invite", timeout=30,
                               json={"token": token, "name": "x", "password": "Another123!"})
        assert reused.status_code in (404, 410), f"invite token reusable: {reused.status_code}"

    def test_invalid_invite_token_404(self):
        g = requests.get(f"{BASE_URL}/api/auth/invite/{uuid.uuid4().hex}", timeout=30)
        assert g.status_code in (404, 400)


# ── password lifecycle on a disposable user ──────────────────────────────────
@pytest.fixture
def disposable_user(admin_cookies):
    email = f"test_iter112_pwd_{uuid.uuid4().hex[:6]}@example.com"
    pwd = "InitialPass123!"
    r = requests.post(f"{BASE_URL}/api/admin/users", cookies=admin_cookies, timeout=60,
                      json={"email": email, "name": "TEST Iter112 Pwd", "role": "attendee",
                            "password": pwd})
    assert r.status_code == 200, r.text[:300]
    yield {"email": email, "password": pwd}
    purge_user(email)


class TestPasswordLifecycle:
    def test_forgot_then_reset_round_trip(self, disposable_user):
        email = disposable_user["email"]
        old_pwd = disposable_user["password"]
        r = requests.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": email}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert "reset link" in r.json()["message"].lower()
        tok = db_row("SELECT token, used FROM password_reset_tokens WHERE email=$1", email)
        assert tok, "no reset token persisted"
        assert tok["used"] is False

        new_pwd = "ResetPass456!"
        rr = requests.post(f"{BASE_URL}/api/auth/reset-password", timeout=60,
                           json={"token": tok["token"], "new_password": new_pwd})
        assert rr.status_code == 200, rr.text[:300]
        row = db_row("SELECT supabase_password_set, must_change_password FROM users WHERE email=$1", email)
        assert row["supabase_password_set"] is True
        assert row["must_change_password"] is False

        assert login(email, new_pwd).status_code == 200, "new password does not work"
        old = login(email, old_pwd)
        assert old.status_code == 401, f"old password still valid after reset: {old.status_code}"
        clear_rate_limits()

        again = requests.post(f"{BASE_URL}/api/auth/reset-password", timeout=30,
                              json={"token": tok["token"], "new_password": "Yetanother789!"})
        assert again.status_code == 400, "reset token reusable"

    def test_reset_password_weak_password_rejected(self, disposable_user):
        email = disposable_user["email"]
        requests.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": email}, timeout=60)
        tok = db_row("SELECT token FROM password_reset_tokens WHERE email=$1", email)
        rr = requests.post(f"{BASE_URL}/api/auth/reset-password", timeout=30,
                           json={"token": tok["token"], "new_password": "weak"})
        assert rr.status_code == 400

    def test_forgot_password_unknown_email_does_not_leak(self):
        r = requests.post(f"{BASE_URL}/api/auth/forgot-password", timeout=60,
                          json={"email": f"nosuch-{uuid.uuid4().hex[:6]}@example.com"})
        assert r.status_code == 200
        assert "reset link" in r.json()["message"].lower()

    def test_change_password_flow(self, disposable_user):
        email = disposable_user["email"]
        old_pwd = disposable_user["password"]
        cookies = login_cookies(email, old_pwd)

        bad = requests.post(f"{BASE_URL}/api/auth/change-password", cookies=cookies, timeout=60,
                            json={"current_password": "WrongCurrent123!", "new_password": "Changed789!"})
        assert bad.status_code == 400, f"wrong current_password accepted: {bad.status_code}"

        new_pwd = "Changed789!x"
        ok = requests.post(f"{BASE_URL}/api/auth/change-password", cookies=cookies, timeout=60,
                           json={"current_password": old_pwd, "new_password": new_pwd})
        assert ok.status_code == 200, ok.text[:300]
        row = db_row("SELECT supabase_password_set FROM users WHERE email=$1", email)
        assert row["supabase_password_set"] is True

        assert login(email, new_pwd).status_code == 200
        assert login(email, old_pwd).status_code == 401
        clear_rate_limits()

    def test_change_password_after_supabase_migration_uses_supabase_check(self, disposable_user):
        """Second change-password on an already-Supabase-backed user must verify
        the current password against Supabase (not the stale bcrypt hash)."""
        email = disposable_user["email"]
        p1 = disposable_user["password"]
        p2 = "SecondPass123!"
        c = login_cookies(email, p1)
        assert requests.post(f"{BASE_URL}/api/auth/change-password", cookies=c, timeout=60,
                             json={"current_password": p1, "new_password": p2}).status_code == 200
        c2 = login_cookies(email, p2)
        p3 = "ThirdPass123!"
        r = requests.post(f"{BASE_URL}/api/auth/change-password", cookies=c2, timeout=60,
                          json={"current_password": p2, "new_password": p3})
        assert r.status_code == 200, f"second change-password failed: {r.text[:300]}"
        assert login(email, p3).status_code == 200
        assert login(email, p2).status_code == 401
        clear_rate_limits()


# ── non-auth regression ──────────────────────────────────────────────────────
class TestNonAuthRegression:
    def test_auth_me(self, admin_cookies):
        r = requests.get(f"{BASE_URL}/api/auth/me", cookies=admin_cookies, timeout=30)
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN[0]
        assert "_id" not in re.sub(r'"[a-z_]*_id"', "", r.text)

    @pytest.mark.parametrize("path", [
        "/api/dashboard/",
        "/api/meetings/",
        "/api/admin/users",
        "/api/admin/standards",
        "/api/org/structure",
        "/api/org/settings",
        "/api/org/branding",
    ])
    def test_core_endpoints_ok(self, admin_cookies, path):
        r = requests.get(f"{BASE_URL}{path}", cookies=admin_cookies, timeout=60)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
        assert "_id" not in re.sub(r'"[a-z_]*_id"', "", r.text), f"{path} leaks mongo _id"

    def test_meetings_crud(self, admin_cookies):
        payload = {"title": "TEST_iter112 meeting", "date": datetime.now(timezone.utc).isoformat(),
                   "meeting_type": "supervision"}
        r = requests.post(f"{BASE_URL}/api/meetings/", cookies=admin_cookies, json=payload, timeout=60)
        assert r.status_code in (200, 201), r.text[:300]
        mid = r.json().get("id")
        assert mid
        g = requests.get(f"{BASE_URL}/api/meetings/{mid}", cookies=admin_cookies, timeout=60)
        assert g.status_code == 200
        assert g.json()["title"] == payload["title"]
        d = requests.delete(f"{BASE_URL}/api/meetings/{mid}", cookies=admin_cookies, timeout=60)
        assert d.status_code in (200, 204), d.text[:200]
        g2 = requests.get(f"{BASE_URL}/api/meetings/{mid}", cookies=admin_cookies, timeout=60)
        assert g2.status_code == 404

    def test_protected_endpoint_without_cookie_401(self):
        r = requests.get(f"{BASE_URL}/api/auth/me", timeout=30)
        assert r.status_code == 401
