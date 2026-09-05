"""
SEC-DB-001 regression tests: verify that access tokens carry the `org_id` JWT claim
after login / MFA / refresh / accept-invite, that get_current_user honours it,
and that pre-fix tokens (missing the claim) cleanly return 401.
"""
import os
import time
import jwt
import psycopg2
import bcrypt
import requests
import pytest

def _read_env(path, key):
    with open(path) as f:
        for line in f:
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError(f"{key} not in {path}")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL") or _read_env("/app/frontend/.env", "REACT_APP_BACKEND_URL")
BASE_URL = BASE_URL.rstrip("/")
JWT_SECRET = "supervision2_jwt_secret_d5f8e9a3b2c1f4e7a8b9c0d1e2f3a4b5c6d7e8f9"
EXPECTED_ORG_ID = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"  # Test Company

# --- helpers -----------------------------------------------------------------

def _pg_conn():
    # Read Supabase pooler URL from backend .env
    with open("/app/backend/.env") as f:
        for line in f:
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"')
                return psycopg2.connect(url)
    raise RuntimeError("DATABASE_URL not found")


def _force_mfa_code(email: str, code: str = "123456"):
    """Overwrite DB mfa_code with a known bcrypt hash so we can complete MFA."""
    h = bcrypt.hashpw(code.encode(), bcrypt.gensalt()).decode()
    conn = _pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET mfa_code=%s, mfa_code_expires_at=NOW() + INTERVAL '10 minutes' "
                "WHERE email=%s",
                (h, email),
            )
        conn.commit()
    finally:
        conn.close()


def _login(session: requests.Session, email: str, password: str) -> dict:
    """Log in (handling MFA if required). Returns the final /login response JSON
    after MFA verification. Cookies are stored on `session`."""
    r = session.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    if data.get("requires_mfa"):
        _force_mfa_code(email)
        r2 = session.post(
            f"{BASE_URL}/api/auth/verify-mfa",
            json={"mfa_session": data["mfa_session"], "code": "123456"},
            timeout=30,
        )
        assert r2.status_code == 200, f"MFA verify failed: {r2.status_code} {r2.text}"
        data = r2.json()
    return data


def _decode(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])


# --- login tests -------------------------------------------------------------

@pytest.mark.parametrize("email,password,expected_org_id", [
    ("admin@supervision.com", "Admin123!", EXPECTED_ORG_ID),
    ("manager@supervision.com", "Manager123!", EXPECTED_ORG_ID),
    ("user@supervision.com", "AnotherNew789!", EXPECTED_ORG_ID),
])
def test_login_token_has_org_id_claim(email, password, expected_org_id):
    s = requests.Session()
    _login(s, email, password)
    token = s.cookies.get("supervision_access")
    assert token, "No access cookie set"
    payload = _decode(token)
    assert payload.get("type") == "access"
    assert payload.get("sub")
    assert "org_id" in payload, "org_id claim MISSING from access token"
    assert payload["org_id"] == expected_org_id, f"org_id mismatch: {payload['org_id']}"

    # /auth/me should also work with the org-scoped connection now.
    me = s.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert me.status_code == 200, f"/auth/me failed: {me.status_code} {me.text}"
    body = me.json()
    assert body["email"] == email


def test_super_admin_login_token_has_org_id_null():
    s = requests.Session()
    _login(s, "superadmin@1two.one", "NewPass123!")
    token = s.cookies.get("supervision_access")
    assert token
    payload = _decode(token)
    assert "org_id" in payload
    assert payload["org_id"] is None, f"super_admin org_id should be null, got {payload['org_id']}"
    # super_admin scoped endpoint (uses with_admin fallback branch)
    orgs = s.get(f"{BASE_URL}/api/super-admin/orgs", timeout=15)
    assert orgs.status_code == 200, f"super-admin/orgs failed: {orgs.status_code} {orgs.text}"


# --- refresh tests -----------------------------------------------------------

@pytest.mark.parametrize("email,password,expected_org_id", [
    ("admin@supervision.com", "Admin123!", EXPECTED_ORG_ID),
    ("manager@supervision.com", "Manager123!", EXPECTED_ORG_ID),
    ("user@supervision.com", "AnotherNew789!", EXPECTED_ORG_ID),
])
def test_refresh_token_mints_new_access_with_org_id(email, password, expected_org_id):
    s = requests.Session()
    _login(s, email, password)
    old_access = s.cookies.get("supervision_access")
    time.sleep(1)  # ensure different iat
    r = s.post(f"{BASE_URL}/api/auth/refresh", timeout=15)
    assert r.status_code == 200, f"refresh failed: {r.status_code} {r.text}"
    new_access = s.cookies.get("supervision_access")
    assert new_access and new_access != old_access, "access cookie not rotated"
    payload = _decode(new_access)
    assert payload.get("org_id") == expected_org_id


def test_refresh_super_admin_token_has_org_id_null():
    s = requests.Session()
    _login(s, "superadmin@1two.one", "NewPass123!")
    r = s.post(f"{BASE_URL}/api/auth/refresh", timeout=15)
    assert r.status_code == 200, r.text
    payload = _decode(s.cookies.get("supervision_access"))
    assert "org_id" in payload
    assert payload["org_id"] is None


# --- old-token migration path ------------------------------------------------

def test_pre_fix_token_without_org_id_returns_401():
    """Craft a valid-signature access token missing the org_id claim (as a
    pre-fix token would look) and confirm the API returns a clean 401 with the
    session-expired message — no 500, no bypass."""
    s = requests.Session()
    _login(s, "admin@supervision.com", "Admin123!")
    real = s.cookies.get("supervision_access")
    real_payload = _decode(real)
    now = int(time.time())
    crafted = {
        "sub": real_payload["sub"],
        "email": real_payload["email"],
        "type": "access",
        "pwd_ts": real_payload.get("pwd_ts", 0),
        "iat": now,
        "exp": now + 600,
        # NOTE: intentionally NO "org_id" key
    }
    tok = jwt.encode(crafted, JWT_SECRET, algorithm="HS256")

    s2 = requests.Session()
    s2.cookies.set("supervision_access", tok, domain=BASE_URL.split("://")[1])
    r = s2.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert r.status_code == 401, f"expected 401, got {r.status_code} body={r.text}"
    # Message must be the session-expired variant (drives frontend silent refresh)
    body = r.json()
    detail = body.get("detail", "")
    assert "sign in again" in detail.lower() or "session expired" in detail.lower(), \
        f"Unexpected detail: {detail}"


def test_pre_fix_token_super_admin_case_null_still_works():
    """org_id=None in the payload is DIFFERENT from missing key — super_admin
    tokens legitimately have org_id=null and must NOT trigger the 401."""
    s = requests.Session()
    _login(s, "superadmin@1two.one", "NewPass123!")
    payload = _decode(s.cookies.get("supervision_access"))
    assert "org_id" in payload and payload["org_id"] is None
    # And /auth/me works
    me = s.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert me.status_code == 200


# --- RBAC unaffected ---------------------------------------------------------

def test_attendee_forbidden_on_admin_endpoint():
    s = requests.Session()
    _login(s, "user@supervision.com", "AnotherNew789!")
    r = s.get(f"{BASE_URL}/api/super-admin/orgs", timeout=15)
    assert r.status_code == 403, f"expected 403, got {r.status_code}"


# --- smoke: representative protected endpoints work for each role ------------

@pytest.mark.parametrize("email,password", [
    ("admin@supervision.com", "Admin123!"),
    ("manager@supervision.com", "Manager123!"),
    ("user@supervision.com", "AnotherNew789!"),
])
def test_smoke_common_endpoints(email, password):
    s = requests.Session()
    _login(s, email, password)
    for path in ["/api/auth/me", "/api/meetings", "/api/teams"]:
        r = s.get(f"{BASE_URL}{path}", timeout=20)
        assert r.status_code in (200, 404), f"{email} {path} -> {r.status_code} {r.text[:200]}"
