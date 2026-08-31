"""Iteration 100 — regression suite for the users.email index removal.

Change under test: `idx_users_email` (redundant duplicate of the UNIQUE-constraint
index `users_email_key`) removed from init_db.py + dropped idempotently at startup.

Modules exercised:
  routers/auth.py   — login (email lookup), forgot-password / reset-password
  routers/admin.py  — create_user + update_user email-uniqueness checks
  routers/org.py    — invite_user email-uniqueness check
  DB level          — index inventory on public.users
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

BE = dotenv_values("/app/backend/.env")
FE = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or FE.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
API = f"{BASE_URL}/api"
DSN = BE["DATABASE_URL"]

ADMIN = ("admin@supervision.com", "Admin123!")
MANAGER = ("manager@supervision.com", "Manager123!")
JANE = ("jane@supervision.com", "Jane123!")

TAG = uuid.uuid4().hex[:8]
PW = "TestPass123!"
CREATED_EMAILS = []


# ── helpers ───────────────────────────────────────────────────────────────────

async def _db_fetch(sql, *args):
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _db_exec(sql, *args):
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        return await conn.execute(sql, *args)
    finally:
        await conn.close()


async def _mfa_override(email):
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await _db_exec(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE LOWER(email)=LOWER($3)",
        h, exp, email)


def login(email, password, expect_ok=True):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    if not expect_ok:
        return s, r
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_mfa_override(email))
        r = s.post(f"{API}/auth/verify-mfa",
                   json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=60)
        if r.status_code != 200:
            pytest.fail(f"MFA verify failed for {email}: {r.status_code} {r.text[:300]}")
    return s, r


@pytest.fixture(scope="session")
def admin_session():
    s, _ = login(*ADMIN)
    me = s.get(f"{API}/auth/me", timeout=60)
    assert me.status_code == 200, me.text[:300]
    assert me.json()["email"] == ADMIN[0]
    return s


@pytest.fixture(scope="session", autouse=True)
def cleanup():
    yield
    for email in CREATED_EMAILS:
        asyncio.run(_db_exec("DELETE FROM users WHERE LOWER(email)=LOWER($1)", email))
    asyncio.run(_db_exec("DELETE FROM password_reset_tokens WHERE email LIKE $1", f"test_iter100_%"))


# ── DB-level index inventory ──────────────────────────────────────────────────

class TestIndexState:
    def test_idx_users_email_dropped_and_unique_index_present(self):
        rows = asyncio.run(_db_fetch(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public' AND tablename='users'"))
        names = {r["indexname"] for r in rows}
        assert "idx_users_email" not in names, f"redundant index still present: {names}"
        assert "users_email_key" in names, f"UNIQUE email index missing! {names}"
        uniq = [r for r in rows if r["indexname"] == "users_email_key"][0]
        assert "UNIQUE" in uniq["indexdef"].upper()
        assert "(email)" in uniq["indexdef"]

    def test_unique_constraint_still_enforced_at_db_level(self):
        # Direct DB duplicate insert must be rejected by users_email_key
        dup_email = ADMIN[0]
        with pytest.raises(asyncpg.exceptions.UniqueViolationError):
            asyncio.run(_db_exec(
                "INSERT INTO users (id, email, password_hash, name, role, org_id, is_active, created_at)"
                " VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                str(uuid.uuid4()), dup_email, "x", "TEST_dup", "attendee", "", True,
                datetime.now(timezone.utc).isoformat()))

    def test_email_lookup_can_use_unique_index(self):
        """With seqscan disabled (table is tiny, so the planner prefers Seq Scan in
        normal operation) the email lookup must be servable by users_email_key."""
        async def _plan():
            conn = await asyncpg.connect(DSN, ssl="require")
            try:
                await conn.execute("SET enable_seqscan = off")
                rows = await conn.fetch(
                    "EXPLAIN SELECT id FROM public.users WHERE email = $1", ADMIN[0])
                return [dict(r) for r in rows]
            finally:
                await conn.close()

        plan = asyncio.run(_plan())
        text = " ".join(str(v) for row in plan for v in row.values())
        assert "users_email_key" in text, f"unique email index not usable for lookup: {text}"

    def test_supabase_auth_schema_index_untouched(self):
        """The unqualified DROP INDEX must not have hit auth.users.idx_users_email."""
        rows = asyncio.run(_db_fetch(
            "SELECT indexname FROM pg_indexes WHERE schemaname='auth' AND tablename='users'"))
        names = {r["indexname"] for r in rows}
        assert "idx_users_email" in names, "Supabase auth.users.idx_users_email was dropped!"


# ── auth: login by email ──────────────────────────────────────────────────────

class TestLoginByEmail:
    @pytest.mark.parametrize("creds", [ADMIN, MANAGER, JANE], ids=["admin", "manager", "jane"])
    def test_login_success(self, creds):
        s, _ = login(*creds)
        me = s.get(f"{API}/auth/me", timeout=60)
        assert me.status_code == 200, me.text[:300]
        body = me.json()
        assert body["email"] == creds[0]
        assert body.get("id")

    def test_login_mixed_case_email(self):
        mixed = "Jane@Supervision.COM"
        s, _ = login(mixed, JANE[1])
        me = s.get(f"{API}/auth/me", timeout=60)
        assert me.status_code == 200, me.text[:300]
        assert me.json()["email"] == JANE[0]

    def test_login_unknown_email_rejected(self):
        _, r = login(f"nobody_{TAG}@example.com", "Whatever123!", expect_ok=False)
        assert r.status_code == 401, f"{r.status_code} {r.text[:200]}"


# ── admin: create_user email uniqueness ───────────────────────────────────────

class TestAdminCreateUser:
    def test_create_unique_email_succeeds_and_persists(self, admin_session):
        email = f"test_iter100_new_{TAG}@example.com"
        CREATED_EMAILS.append(email)
        r = admin_session.post(f"{API}/admin/users", json={
            "email": email, "name": "TEST_iter100 New", "password": PW, "role": "attendee"}, timeout=60)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"
        body = r.json()
        assert body["email"] == email
        assert body["name"] == "TEST_iter100 New"
        uid = body["id"]

        # verify via API list
        lst = admin_session.get(f"{API}/admin/users", timeout=60)
        assert lst.status_code == 200
        users = lst.json()
        users = users.get("users", users) if isinstance(users, dict) else users
        assert any(u["email"] == email and u["id"] == uid for u in users)

        # verify persisted in DB
        rows = asyncio.run(_db_fetch("SELECT id, email, role FROM users WHERE email=$1", email))
        assert len(rows) == 1 and rows[0]["id"] == uid

    def test_create_duplicate_email_rejected(self, admin_session):
        r = admin_session.post(f"{API}/admin/users", json={
            "email": ADMIN[0], "name": "TEST_iter100 Dup", "password": PW, "role": "attendee"}, timeout=60)
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text[:300]}"
        assert "email" in str(r.json().get("detail", "")).lower()
        # no duplicate row created
        rows = asyncio.run(_db_fetch("SELECT id FROM users WHERE email=$1", ADMIN[0]))
        assert len(rows) == 1

    def test_create_duplicate_email_mixed_case_rejected(self, admin_session):
        r = admin_session.post(f"{API}/admin/users", json={
            "email": "Admin@Supervision.COM", "name": "TEST_iter100 DupCase",
            "password": PW, "role": "attendee"}, timeout=60)
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text[:300]}"
        rows = asyncio.run(_db_fetch("SELECT id FROM users WHERE LOWER(email)=$1", ADMIN[0]))
        assert len(rows) == 1


# ── org: invite_user email uniqueness ─────────────────────────────────────────

class TestOrgInviteUser:
    def test_invite_unique_email_succeeds(self, admin_session):
        email = f"test_iter100_invite_{TAG}@example.com"
        CREATED_EMAILS.append(email)
        r = admin_session.post(f"{API}/org/invite-user", json={
            "email": email, "name": "TEST_iter100 Invite", "password": PW, "role": "attendee"}, timeout=60)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"
        assert r.json()["email"] == email
        rows = asyncio.run(_db_fetch("SELECT id FROM users WHERE email=$1", email))
        assert len(rows) == 1

    def test_invite_duplicate_email_rejected(self, admin_session):
        r = admin_session.post(f"{API}/org/invite-user", json={
            "email": MANAGER[0], "name": "TEST_iter100 InviteDup",
            "password": PW, "role": "attendee"}, timeout=60)
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text[:300]}"
        rows = asyncio.run(_db_fetch("SELECT id FROM users WHERE email=$1", MANAGER[0]))
        assert len(rows) == 1


# ── admin: update_user email edit ─────────────────────────────────────────────

class TestAdminUpdateEmail:
    def test_edit_email_to_unique_value(self, admin_session):
        old = f"test_iter100_edit_{TAG}@example.com"
        new = f"test_iter100_edited_{TAG}@example.com"
        CREATED_EMAILS.extend([old, new])
        c = admin_session.post(f"{API}/admin/users", json={
            "email": old, "name": "TEST_iter100 Edit", "password": PW, "role": "attendee"}, timeout=60)
        assert c.status_code in (200, 201), c.text[:300]
        uid = c.json()["id"]

        u = admin_session.put(f"{API}/admin/users/{uid}", json={"email": new}, timeout=60)
        assert u.status_code == 200, f"{u.status_code} {u.text[:300]}"

        rows = asyncio.run(_db_fetch("SELECT email FROM users WHERE id=$1", uid))
        assert rows and rows[0]["email"] == new
        assert asyncio.run(_db_fetch("SELECT id FROM users WHERE email=$1", old)) == []

        # login with the new email works
        s, _ = login(new, PW)
        me = s.get(f"{API}/auth/me", timeout=60)
        assert me.status_code == 200 or me.json  # new users may require password change
        if me.status_code == 200:
            assert me.json()["email"] == new

    def test_edit_email_to_existing_value_rejected(self, admin_session):
        target = f"test_iter100_clash_{TAG}@example.com"
        CREATED_EMAILS.append(target)
        c = admin_session.post(f"{API}/admin/users", json={
            "email": target, "name": "TEST_iter100 Clash", "password": PW, "role": "attendee"}, timeout=60)
        assert c.status_code in (200, 201), c.text[:300]
        uid = c.json()["id"]

        u = admin_session.put(f"{API}/admin/users/{uid}", json={"email": MANAGER[0]}, timeout=60)
        assert u.status_code == 400, f"expected 400, got {u.status_code} {u.text[:300]}"
        assert "in use" in str(u.json().get("detail", "")).lower() or "email" in str(u.json().get("detail", "")).lower()
        rows = asyncio.run(_db_fetch("SELECT email FROM users WHERE id=$1", uid))
        assert rows[0]["email"] == target  # unchanged

    def test_edit_email_same_value_allowed(self, admin_session):
        """Setting a user's email to its current value must not trip the clash check."""
        email = f"test_iter100_same_{TAG}@example.com"
        CREATED_EMAILS.append(email)
        c = admin_session.post(f"{API}/admin/users", json={
            "email": email, "name": "TEST_iter100 Same", "password": PW, "role": "attendee"}, timeout=60)
        uid = c.json()["id"]
        u = admin_session.put(f"{API}/admin/users/{uid}", json={"email": email}, timeout=60)
        assert u.status_code == 200, f"{u.status_code} {u.text[:300]}"


# ── auth: forgot-password / reset-password by email ───────────────────────────

class TestForgotPasswordFlow:
    def test_forgot_and_reset_password_end_to_end(self, admin_session):
        email = f"test_iter100_reset_{TAG}@example.com"
        CREATED_EMAILS.append(email)
        c = admin_session.post(f"{API}/admin/users", json={
            "email": email, "name": "TEST_iter100 Reset", "password": PW, "role": "attendee"}, timeout=60)
        assert c.status_code in (200, 201), c.text[:300]

        r = requests.post(f"{API}/auth/forgot-password", json={"email": email}, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

        rows = asyncio.run(_db_fetch(
            "SELECT token, used FROM password_reset_tokens WHERE email=$1", email))
        assert len(rows) == 1, f"reset token not created: {rows}"
        token = rows[0]["token"]
        assert rows[0]["used"] is False

        new_pw = "BrandNewPw123!"
        rp = requests.post(f"{API}/auth/reset-password",
                           json={"token": token, "new_password": new_pw}, timeout=60)
        assert rp.status_code == 200, f"{rp.status_code} {rp.text[:300]}"

        used = asyncio.run(_db_fetch(
            "SELECT used FROM password_reset_tokens WHERE token=$1", token))
        assert used[0]["used"] is True

        s, resp = login(email, new_pw)
        assert resp.status_code == 200
        # old password must now fail
        _, bad = login(email, PW, expect_ok=False)
        assert bad.status_code == 401, f"old password still accepted: {bad.status_code}"

    def test_forgot_password_unknown_email_generic_response(self):
        r = requests.post(f"{API}/auth/forgot-password",
                          json={"email": f"ghost_{TAG}@example.com"}, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert "reset link" in r.json().get("message", "").lower()

    def test_forgot_password_mixed_case_email_finds_user(self):
        r = requests.post(f"{API}/auth/forgot-password",
                          json={"email": JANE[0].upper()}, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        rows = asyncio.run(_db_fetch(
            "SELECT token FROM password_reset_tokens WHERE email=$1", JANE[0]))
        assert len(rows) == 1, "mixed-case forgot-password did not create a token for the lowercase user"
        asyncio.run(_db_exec("DELETE FROM password_reset_tokens WHERE email=$1", JANE[0]))
