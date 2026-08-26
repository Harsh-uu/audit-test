"""
Security Tests — JWT Attacks & IDOR (Insecure Direct Object Reference)
=======================================================================
Covers the two gaps previously targeted at Strix pentest:
  1. JWT weaknesses — algorithm confusion, signature bypass, role escalation,
     token-type confusion, expired/malformed tokens.
  2. IDOR — horizontal privilege (same org), vertical privilege (role escalation),
     and cross-tenant (Org A token accessing Org B resources).

Run:
    cd /app && pytest backend/tests/test_security_jwt_idor.py -v --tb=short

All tests are self-contained. Cross-tenant fixtures create and clean up a
second org directly in the DB so no MFA-gated super-admin login is required.
"""

import os
import sys
import uuid
import time
import json
import asyncio
import asyncpg
import pytest
import requests
import jwt as pyjwt
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "http://localhost:8001",
).rstrip("/")
# Strip /api suffix if present — this file constructs its own /api/... paths
if BASE_URL.endswith("/api"):
    BASE_URL = BASE_URL[:-4]

JWT_SECRET    = os.environ["JWT_SECRET"]
JWT_ALGORITHM = "HS256"
_PG_DSN       = os.environ.get("DATABASE_URL")  # asyncpg needs the PostgreSQL DSN

# Test accounts (from /app/memory/test_credentials.md)
STAFF_EMAIL    = "user@supervision.com"
STAFF_PASS     = "Staff123!"
MANAGER_EMAIL  = "manager@supervision.com"
MANAGER_PASS   = "Manager123!"


# ── Helpers ───────────────────────────────────────────────────────────────────

def api(path: str) -> str:
    """Prefix path with /api for routing through Kubernetes ingress."""
    return f"{BASE_URL}/api{path}"


# ── Token cache (avoids triggering IP rate-limit across 24 tests) ─────────────

_token_cache: dict[str, str] = {}


def login(email: str, password: str) -> str:
    """Login and return the access token.
    P3b: tokens now in HttpOnly cookies. We extract the cookie value for tests.
    The backend still accepts Bearer tokens as a fallback, so we pass the
    cookie value in Authorization: Bearer headers for all security test requests.
    """
    r = requests.post(api("/auth/login"), json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"Login failed for {email}: {r.text}"
    data = r.json()
    # P3b: token is now the supervision_access cookie, not in the response body
    token = r.cookies.get("supervision_access")
    assert token, f"No supervision_access cookie in login response for {email}. Body: {data}"
    return token


def login_cached(email: str, password: str) -> str:
    """Return a cached token; avoids repeated login calls that trigger the IP rate-limiter."""
    if email not in _token_cache:
        _token_cache[email] = login(email, password)
    return _token_cache[email]


def forge_token(overrides: dict, secret: str = JWT_SECRET, algorithm: str = JWT_ALGORITHM) -> str:
    """Create a JWT with custom payload fields. Defaults to a well-formed access payload.
    pwd_ts defaults to 0 to match test-inserted users whose password_changed_at is NULL
    (i.e. DB-side pwd_ts also resolves to 0) — override via `overrides` if a test user
    has a real password_changed_at set."""
    now = int(time.time())
    payload = {
        "sub":  str(uuid.uuid4()),   # non-existent user by default
        "type": "access",
        "exp":  now + 3600,
        "iat":  now,
        "pwd_ts": 0,
    }
    payload.update(overrides)
    return pyjwt.encode(payload, secret, algorithm=algorithm)


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── DB helpers for cross-tenant fixture ───────────────────────────────────────

def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _direct_exec(sql: str, *args):
    """Execute SQL using a fresh direct connection — avoids event-loop pool conflicts in teardown."""
    conn = await asyncpg.connect(_PG_DSN)
    try:
        await conn.execute(sql, *args)
    finally:
        await conn.close()


# ── Session-scoped fixtures ───────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def clear_rate_limits_and_settle():
    """
    Wipe login_attempts before the suite so the IP rate-limiter doesn't block
    repeated test logins. Sleep briefly so the server pool settles after the
    direct DB write before the first request is made.
    """
    _run_async(_direct_exec("DELETE FROM login_attempts"))
    time.sleep(2)   # let the DB pool settle after the direct write
    yield


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — JWT ATTACK TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestJWTAttacks:
    """
    Every test verifies that a crafted/invalid token is rejected with 401.
    A protected endpoint that would return 200 for a valid token is used as
    the probe: GET /api/auth/me.
    """

    PROBE = "/auth/me"

    def test_no_token_returns_401(self):
        """Missing Authorization header → 401."""
        r = requests.get(api(self.PROBE), timeout=10)
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"
        print("PASS: missing token → 401")

    def test_malformed_bearer_returns_401(self):
        """Garbage string in Authorization header → 401."""
        r = requests.get(api(self.PROBE), headers={"Authorization": "Bearer not.a.jwt"}, timeout=10)
        assert r.status_code == 401
        print("PASS: malformed token → 401")

    def test_alg_none_attack(self):
        """
        alg=none attack: strip the signature, change algorithm to 'none'.
        PyJWT with algorithms=['HS256'] must reject this outright.
        """
        # Build a valid-looking payload and encode with HS256 first
        now = int(time.time())
        payload = {"sub": str(uuid.uuid4()), "type": "access", "exp": now + 3600, "iat": now}
        # Manually craft the none-alg token (PyJWT refuses to encode alg=none directly)
        import base64
        header  = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
        body    = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        none_token = f"{header}.{body}."          # empty signature
        r = requests.get(api(self.PROBE), headers=auth_header(none_token), timeout=10)
        assert r.status_code == 401, f"alg=none accepted! Got {r.status_code}: {r.text}"
        print("PASS: alg=none token → 401")

    def test_wrong_secret_returns_401(self):
        """Token signed with a completely different secret → 401."""
        token = forge_token({}, secret="completely-wrong-secret-xxxxxxxxxxx")
        r = requests.get(api(self.PROBE), headers=auth_header(token), timeout=10)
        assert r.status_code == 401
        print("PASS: wrong-secret token → 401")

    def test_expired_token_returns_401(self):
        """Token with exp in the past → 401."""
        token = forge_token({"exp": int(time.time()) - 10})
        r = requests.get(api(self.PROBE), headers=auth_header(token), timeout=10)
        assert r.status_code == 401
        detail = r.json().get("detail", "")
        assert "expired" in detail.lower() or r.status_code == 401
        print("PASS: expired token → 401")

    def test_refresh_token_rejected_on_protected_endpoint(self):
        """A refresh token (type='refresh') must not be accepted on guarded endpoints."""
        token = forge_token({"type": "refresh"})
        r = requests.get(api(self.PROBE), headers=auth_header(token), timeout=10)
        assert r.status_code == 401
        print("PASS: refresh token on /auth/me → 401")

    def test_mfa_pending_token_rejected(self):
        """An mfa_pending token must not grant access."""
        token = forge_token({"type": "mfa_pending"})
        r = requests.get(api(self.PROBE), headers=auth_header(token), timeout=10)
        assert r.status_code == 401
        print("PASS: mfa_pending token → 401")

    def test_missing_type_claim_rejected(self):
        """Token with no 'type' claim → 401 (fails the type != 'access' check)."""
        token = forge_token({"type": None})
        # Remove the type key entirely
        now = int(time.time())
        payload = {"sub": str(uuid.uuid4()), "exp": now + 3600, "iat": now}
        token = pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        r = requests.get(api(self.PROBE), headers=auth_header(token), timeout=10)
        assert r.status_code == 401
        print("PASS: missing type claim → 401")

    def test_nonexistent_sub_returns_401(self):
        """Valid signature, valid type, but sub maps to no real user → 401."""
        token = forge_token({"sub": str(uuid.uuid4()), "type": "access"})
        r = requests.get(api(self.PROBE), headers=auth_header(token), timeout=10)
        assert r.status_code == 401
        print("PASS: non-existent user sub → 401")

    def test_role_escalation_via_jwt_payload(self):
        """
        Critical: attacker signs a token with the REAL secret but embeds
        role='admin' for a known attendee's sub.
        Expected: role in response must be 'attendee' (from DB, not JWT payload).
        deps.py returns the DB row — the JWT payload role is ignored.
        """
        # Step 1: get real attendee user_id via login (decode the real token to
        # reuse its current pwd_ts, so the forged token below isn't rejected as
        # stale by the SEC-001 access-token pwd_ts check — this test targets
        # role-injection specifically, not token freshness).
        staff_token = login_cached(STAFF_EMAIL, STAFF_PASS)
        me = requests.get(api("/auth/me"), headers=auth_header(staff_token), timeout=10).json()
        attendee_id  = me["id"]
        attendee_org = me["org_id"]
        real_pwd_ts = pyjwt.decode(staff_token, JWT_SECRET, algorithms=[JWT_ALGORITHM]).get("pwd_ts", 0)

        # Step 2: forge a token with the real secret, real sub, but role=admin
        now = int(time.time())
        evil_payload = {
            "sub":     attendee_id,
            "type":    "access",
            "exp":     now + 3600,
            "iat":     now,
            "role":    "admin",          # attacker-injected escalated role
            "org_id":  attendee_org,
            "pwd_ts":  real_pwd_ts,
        }
        evil_token = pyjwt.encode(evil_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

        # Step 3: /api/auth/me with the evil token — token DECODES successfully
        r = requests.get(api("/auth/me"), headers=auth_header(evil_token), timeout=10)
        assert r.status_code == 200, f"Expected 200 (token valid), got {r.status_code}: {r.text}"

        # Step 4: the response role MUST be the real DB role, not 'admin'
        returned_role = r.json().get("role")
        assert returned_role != "admin", (
            f"CRITICAL: JWT role escalation succeeded — server returned role='{returned_role}'. "
            "deps.py must pull role from DB, not JWT payload."
        )
        assert returned_role == "attendee"

        # Step 5: confirm evil token cannot reach admin-only endpoint
        r2 = requests.get(api("/admin/users"), headers=auth_header(evil_token), timeout=10)
        assert r2.status_code == 403, (
            f"Admin endpoint accessible with escalated JWT role! Got {r2.status_code}"
        )
        print(f"PASS: JWT role escalation blocked — DB role='{returned_role}' overrides JWT payload")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — IDOR (same-org horizontal privilege)
# ══════════════════════════════════════════════════════════════════════════════

class TestIDORHorizontal:
    """
    Staff user (attendee) must not access meetings/reviews they are not a
    participant in, even within the same org.
    """

    @classmethod
    @pytest.fixture(autouse=True, scope="class")
    def create_manager_only_meeting(cls, request):
        """Create a meeting owned by manager (no attendees) directly in DB; clean up after."""
        async def _setup():
            import database
            await database.create_pool()
            async with database.with_admin() as conn:
                mgr = await conn.fetchrow(
                    "SELECT id, org_id FROM users WHERE email=$1", MANAGER_EMAIL
                )
                assert mgr, "Manager user not found in DB"
                mid = str(uuid.uuid4())
                now = datetime.now(timezone.utc).isoformat()
                await conn.execute(
                    """INSERT INTO meetings (id, org_id, title, date, status, created_by, created_at, attendees)
                       VALUES ($1,$2,'IDOR Horizontal Test Meeting',$3,'draft',$4,$5,'[]'::jsonb)""",
                    mid, mgr["org_id"], datetime.now(timezone.utc).date().isoformat(),
                    mgr["id"], now,
                )
                return mid

        mid = _run_async(_setup())
        request.cls.meeting_id = mid

        yield

        _run_async(_direct_exec("DELETE FROM meetings WHERE id=$1", mid))

    def test_staff_cannot_get_meeting_details(self):
        """Staff not listed as attendee must not fetch meeting details."""
        staff_token = login_cached(STAFF_EMAIL, STAFF_PASS)
        r = requests.get(api(f"/meetings/{self.meeting_id}"), headers=auth_header(staff_token), timeout=10)
        assert r.status_code in (403, 404), (
            f"IDOR: staff accessed manager-only meeting details! Status {r.status_code}"
        )
        print(f"PASS: staff → GET meeting details → {r.status_code}")

    def test_staff_cannot_get_review_data(self):
        """Staff must not read the supervision review/report for a meeting they aren't on."""
        staff_token = login_cached(STAFF_EMAIL, STAFF_PASS)
        r = requests.get(api(f"/review/{self.meeting_id}"), headers=auth_header(staff_token), timeout=10)
        assert r.status_code in (403, 404), (
            f"IDOR: staff read review data for meeting they are not on! Status {r.status_code}"
        )
        print(f"PASS: staff → GET review data → {r.status_code}")

    def test_staff_cannot_get_comments(self):
        """Staff must not read comments on a meeting they aren't on."""
        staff_token = login_cached(STAFF_EMAIL, STAFF_PASS)
        r = requests.get(api(f"/review/{self.meeting_id}/comments"), headers=auth_header(staff_token), timeout=10)
        assert r.status_code in (403, 404), (
            f"IDOR: staff read comments on meeting they are not on! Status {r.status_code}"
        )
        print(f"PASS: staff → GET comments → {r.status_code}")

    def test_staff_cannot_post_comment(self):
        """Staff must not post comments on a meeting they aren't on."""
        staff_token = login_cached(STAFF_EMAIL, STAFF_PASS)
        r = requests.post(
            api(f"/review/{self.meeting_id}/comments"),
            headers=auth_header(staff_token),
            json={"text": "Unauthorized comment from IDOR test"},
            timeout=10,
        )
        assert r.status_code in (403, 404), (
            f"IDOR: staff posted comment on meeting they are not on! Status {r.status_code}"
        )
        print(f"PASS: staff → POST comment → {r.status_code}")

    def test_staff_cannot_trigger_processing(self):
        """Staff must not trigger audio processing on a meeting they aren't on."""
        staff_token = login_cached(STAFF_EMAIL, STAFF_PASS)
        r = requests.post(api(f"/processing/{self.meeting_id}/retry"), headers=auth_header(staff_token), timeout=10)
        assert r.status_code in (403, 404), (
            f"IDOR: staff triggered processing on meeting they are not on! Status {r.status_code}"
        )
        print(f"PASS: staff → POST processing/retry → {r.status_code}")

    def test_staff_cannot_sign_off_meeting(self):
        """Staff must not sign off a meeting — manager/admin only."""
        staff_token = login_cached(STAFF_EMAIL, STAFF_PASS)
        r = requests.post(api(f"/review/{self.meeting_id}/signoff"), headers=auth_header(staff_token), timeout=10)
        assert r.status_code in (403, 404), (
            f"IDOR/privilege: staff signed off a meeting! Status {r.status_code}"
        )
        print(f"PASS: staff → POST signoff → {r.status_code}")

    def test_staff_cannot_access_admin_users(self):
        """Vertical: staff must not access admin user management endpoints."""
        staff_token = login_cached(STAFF_EMAIL, STAFF_PASS)
        r = requests.get(api("/admin/users"), headers=auth_header(staff_token), timeout=10)
        assert r.status_code == 403, (
            f"Privilege escalation: staff accessed /admin/users! Status {r.status_code}"
        )
        print(f"PASS: staff → GET /admin/users → 403")

    def test_staff_cannot_access_team_insights(self):
        """Vertical: staff must not access team analytics."""
        staff_token = login_cached(STAFF_EMAIL, STAFF_PASS)
        r = requests.get(api("/admin/team-insights"), headers=auth_header(staff_token), timeout=10)
        assert r.status_code == 403, (
            f"Privilege escalation: staff accessed /admin/team-insights! Status {r.status_code}"
        )
        print(f"PASS: staff → GET /admin/team-insights → 403")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — IDOR (cross-tenant)
# ══════════════════════════════════════════════════════════════════════════════

class TestIDORCrossTenant:
    """
    Org A token must never access resources belonging to Org B.
    A second org + meeting is created directly in the DB (bypassing MFA-gated
    super-admin login) then cleaned up after the class.
    """

    @classmethod
    @pytest.fixture(autouse=True, scope="class")
    def setup_org_b(cls, request):
        """Create Org B with a meeting in the DB, yield IDs, then tear down."""
        org_b_id      = str(uuid.uuid4())
        org_b_user_id = str(uuid.uuid4())
        meeting_b_id  = str(uuid.uuid4())
        now           = datetime.now(timezone.utc).isoformat()

        async def _setup():
            import database
            await database.create_pool()
            async with database.with_admin() as conn:
                # Insert minimal Org B (schema uses 'status' not 'is_active')
                await conn.execute(
                    """INSERT INTO organisations (id, name, created_at, jurisdiction, service_type, status)
                       VALUES ($1, $2, $3, 'england', 'residential', 'active')
                       ON CONFLICT DO NOTHING""",
                    org_b_id, "IDOR Test Org B (auto-cleanup)", now,
                )
                # Insert a user in Org B
                import bcrypt
                pw_hash = bcrypt.hashpw(b"TestPass999!", bcrypt.gensalt()).decode()
                await conn.execute(
                    """INSERT INTO users (id, org_id, email, password_hash, name, role, is_active, created_at)
                       VALUES ($1,$2,$3,$4,'Org B Test User','admin',TRUE,$5)
                       ON CONFLICT DO NOTHING""",
                    org_b_user_id, org_b_id, f"orgb-test-{org_b_id[:8]}@example.com", pw_hash, now,
                )
                # Insert a meeting owned by Org B
                await conn.execute(
                    """INSERT INTO meetings (id, org_id, title, date, status, created_by, created_at)
                       VALUES ($1,$2,'Org B Private Meeting','2026-08-01','draft',$3,$4)
                       ON CONFLICT DO NOTHING""",
                    meeting_b_id, org_b_id, org_b_user_id, now,
                )

        _run_async(_setup())

        request.cls.meeting_b_id = meeting_b_id
        request.cls.org_b_id     = org_b_id

        yield

        # Teardown — remove all Org B test data
        _run_async(_direct_exec("DELETE FROM meetings      WHERE org_id=$1", org_b_id))
        _run_async(_direct_exec("DELETE FROM users         WHERE org_id=$1", org_b_id))
        _run_async(_direct_exec("DELETE FROM organisations WHERE id=$1",     org_b_id))

    def test_org_a_cannot_list_org_b_meeting(self):
        """Org A token: GET /meetings/{org_b_meeting_id} must return 404 (RLS isolation)."""
        token = login_cached(STAFF_EMAIL, STAFF_PASS)
        r = requests.get(api(f"/meetings/{self.meeting_b_id}"), headers=auth_header(token), timeout=10)
        assert r.status_code == 404, (
            f"CROSS-TENANT IDOR: Org A read Org B meeting! Status {r.status_code}: {r.text}"
        )
        print(f"PASS: cross-tenant → GET meeting → 404")

    def test_org_a_cannot_get_org_b_review_data(self):
        """Org A token: GET /review/{org_b_meeting_id} must return 404."""
        token = login_cached(STAFF_EMAIL, STAFF_PASS)
        r = requests.get(api(f"/review/{self.meeting_b_id}"), headers=auth_header(token), timeout=10)
        assert r.status_code == 404, (
            f"CROSS-TENANT IDOR: Org A read Org B review data! Status {r.status_code}: {r.text}"
        )
        print(f"PASS: cross-tenant → GET review → 404")

    def test_org_a_cannot_get_org_b_comments(self):
        """Org A token: GET /review/{org_b_meeting_id}/comments must return 404."""
        token = login_cached(STAFF_EMAIL, STAFF_PASS)
        r = requests.get(api(f"/review/{self.meeting_b_id}/comments"), headers=auth_header(token), timeout=10)
        assert r.status_code == 404, (
            f"CROSS-TENANT IDOR: Org A read Org B comments! Status {r.status_code}: {r.text}"
        )
        print(f"PASS: cross-tenant → GET comments → 404")

    def test_org_a_cannot_post_org_b_comment(self):
        """Org A token: POST /review/{org_b_meeting_id}/comments must return 404."""
        token = login_cached(STAFF_EMAIL, STAFF_PASS)
        r = requests.post(
            api(f"/review/{self.meeting_b_id}/comments"),
            headers=auth_header(token),
            json={"text": "Cross-tenant comment injection attempt"},
            timeout=10,
        )
        assert r.status_code == 404, (
            f"CROSS-TENANT IDOR: Org A posted comment into Org B meeting! Status {r.status_code}: {r.text}"
        )
        print(f"PASS: cross-tenant → POST comment → 404")

    def test_org_a_cannot_trigger_org_b_processing(self):
        """Org A token: POST /processing/{org_b_meeting_id}/retry must return 404."""
        # Use staff token — this is about cross-tenant isolation, not role
        token = login_cached(STAFF_EMAIL, STAFF_PASS)
        r = requests.post(api(f"/processing/{self.meeting_b_id}/retry"), headers=auth_header(token), timeout=10)
        assert r.status_code in (403, 404), (
            f"CROSS-TENANT IDOR: Org A triggered processing on Org B meeting! Status {r.status_code}: {r.text}"
        )
        print(f"PASS: cross-tenant → POST processing/retry → {r.status_code}")

    def test_org_a_admin_cannot_get_org_b_admin_data(self):
        """
        Org A cannot retrieve Org B's admin/team-insights even if they know Org B's ID.
        Admin endpoints are scoped by the token's org_id from the DB.
        Test using staff (forbidden by role) — confirms the endpoint rejects before any org leak.
        """
        token = login_cached(STAFF_EMAIL, STAFF_PASS)
        r = requests.get(
            api("/admin/team-insights"),
            headers=auth_header(token),
            params={"org_id": self.org_b_id},
            timeout=10,
        )
        assert r.status_code == 403, (
            f"Staff accessed /admin/team-insights! Got {r.status_code}"
        )
        print(f"PASS: cross-tenant → GET team-insights with org_b param → 403 (role block + no data leak)")



# ── P3c: Sign-off Gate ────────────────────────────────────────────────────────

class TestSignOffGate:
    """P3c: Sign-off is blocked when status == in_review (not all attendees reviewed)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create an org + manager + meeting in in_review state for the test."""
        self.org_id  = str(uuid.uuid4())
        self.mgr_id  = str(uuid.uuid4())
        self.mtg_id  = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        async def _setup():
            import database
            await database.create_pool()
            async with database.with_admin() as conn:
                await conn.execute(
                    """INSERT INTO organisations (id, name, created_at, jurisdiction, service_type, status)
                       VALUES ($1, $2, $3, 'england', 'residential', 'active')
                       ON CONFLICT DO NOTHING""",
                    self.org_id, "P3cTestOrg", now,
                )
                import bcrypt
                pw_hash = bcrypt.hashpw(b"P3cTest999!", bcrypt.gensalt()).decode()
                await conn.execute(
                    "INSERT INTO users (id, org_id, email, password_hash, name, role, is_active, created_at) "
                    "VALUES ($1,$2,$3,$4,$5,'manager',TRUE,$6) ON CONFLICT DO NOTHING",
                    self.mgr_id, self.org_id, f"mgr_{self.mgr_id[:8]}@p3c.test", pw_hash, "P3cManager", now,
                )
                attendees = json.dumps([
                    {"name": "Alice Unreviewed", "email": "alice@p3c.test", "reviewed": False}
                ])
                await conn.execute(
                    "INSERT INTO meetings (id, org_id, title, status, attendees, created_by, created_at) "
                    "VALUES ($1,$2,$3,'in_review',$4,$5,$6) ON CONFLICT DO NOTHING",
                    self.mtg_id, self.org_id, "P3cTestMeeting", attendees, self.mgr_id, now,
                )
        _run_async(_setup())
        yield
        # Teardown
        async def _teardown():
            conn = await asyncpg.connect(_PG_DSN)
            try:
                await conn.execute("DELETE FROM meetings WHERE id=$1", self.mtg_id)
                await conn.execute("DELETE FROM users WHERE id=$1", self.mgr_id)
                await conn.execute("DELETE FROM organisations WHERE id=$1", self.org_id)
            finally:
                await conn.close()
        _run_async(_teardown())

    def _mgr_token(self) -> str:
        return forge_token({"sub": self.mgr_id, "type": "access", "email": f"mgr_{self.mgr_id[:8]}@p3c.test"})

    def test_signoff_blocked_when_in_review(self):
        """P3c: sign-off is rejected (400) when status is in_review."""
        token = self._mgr_token()
        r = requests.post(
            api(f"/review/{self.mtg_id}/signoff"),
            headers=auth_header(token),
            timeout=30,
        )
        assert r.status_code == 400, (
            f"P3c FAIL: sign-off was allowed on in_review meeting! "
            f"Got {r.status_code}: {r.text}"
        )
        assert "Pending" in r.json().get("detail", ""), (
            f"P3c FAIL: 400 response missing expected pending-attendees message: {r.text}"
        )
        print(f"PASS P3c: sign-off blocked on in_review meeting → 400 with: {r.json()['detail'][:80]}")

    def test_signoff_allowed_when_all_reviewed(self):
        """P3c: sign-off proceeds (200) once status is 'reviewed'."""
        # Update meeting status + attendee.reviewed=True using direct connection
        async def _set_reviewed():
            conn = await asyncpg.connect(_PG_DSN)
            try:
                attendees = json.dumps([
                    {"name": "Alice Reviewed", "email": "alice@p3c.test", "reviewed": True}
                ])
                await conn.execute(
                    "UPDATE meetings SET status='reviewed', attendees=$1::jsonb WHERE id=$2",
                    attendees, self.mtg_id,
                )
            finally:
                await conn.close()
        _run_async(_set_reviewed())

        token = self._mgr_token()
        r = requests.post(
            api(f"/review/{self.mtg_id}/signoff"),
            headers=auth_header(token),
            timeout=30,
        )
        assert r.status_code == 200, (
            f"P3c FAIL: sign-off was blocked on a fully-reviewed meeting! "
            f"Got {r.status_code}: {r.text}"
        )
        print(f"PASS P3c: sign-off allowed on reviewed meeting → 200")
