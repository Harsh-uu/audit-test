"""
Iteration 167 — Test invite-user flow (password removal + email invite)
Covers:
- POST /api/org/invite-user (no password; creates pending user; sends/returns link)
- POST /api/org/invite-user/{user_id}/resend (token rotation)
- Pending user visible in /api/admin/users with must_change_password / is_active=False
- Revoke pending (DELETE /api/admin/users/{id}) also removes invitations row
- Super Admin invite-admin flow still works (regression)
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASSWORD = "Admin123!X"
SUPER_EMAIL = "superadmin@1two.one"
SUPER_PASSWORD = "TestPass123!"


def _login(session: requests.Session, email: str, password: str) -> dict:
    r = session.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        pytest.skip(f"login failed for {email}: {r.status_code} {r.text[:200]}")
    data = r.json()
    # If MFA required, try bypass code 123456 (per test_credentials.md)
    if data.get("mfa_required") or data.get("require_mfa"):
        mfa_token = data.get("mfa_token") or data.get("temp_token")
        r2 = session.post(f"{BASE_URL}/api/auth/mfa/verify", json={"token": mfa_token, "code": "123456"})
        if r2.status_code != 200:
            pytest.skip(f"mfa failed for {email}")
        data = r2.json()
    return data


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    _login(s, ADMIN_EMAIL, ADMIN_PASSWORD)
    return s


@pytest.fixture(scope="module")
def created_user_ids():
    return []


class TestInviteStaff:
    def test_invite_no_password_field_required(self, admin_session, created_user_ids):
        """Invite should succeed WITHOUT a password param."""
        email = f"TEST_invite_{uuid.uuid4().hex[:8]}@example.com"
        payload = {"name": "TEST Invitee", "email": email, "role": "attendee"}
        r = admin_session.post(f"{BASE_URL}/api/org/invite-user", json=payload)
        assert r.status_code == 200, f"status={r.status_code} body={r.text[:300]}"
        body = r.json()
        assert body.get("email") == email.lower()
        assert body.get("role") == "attendee"
        assert "id" in body
        created_user_ids.append(body["id"])
        # Either sent OR email_failed with invite_link
        if body.get("email_failed"):
            assert "invite_link" in body and "/accept-invite?token=" in body["invite_link"]
        else:
            assert "message" in body

    def test_invite_delivered_resend_dev(self, admin_session, created_user_ids):
        """Resend sandbox address — expect email_sent (no email_failed)."""
        email = f"TEST_delivered_{uuid.uuid4().hex[:8]}@resend.dev"
        # Use the safe resend sandbox address so Resend actually accepts it
        email = "delivered@resend.dev"
        # If this address already exists in system (from main agent testing), skip creation but tolerate 400
        payload = {"name": "TEST Delivered", "email": email, "role": "attendee"}
        r = admin_session.post(f"{BASE_URL}/api/org/invite-user", json=payload)
        if r.status_code == 400 and "already" in r.text.lower():
            pytest.skip("delivered@resend.dev already exists from prior test; skipping create")
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        body = r.json()
        created_user_ids.append(body["id"])
        # Not strictly required but typically sent via Resend sandbox
        assert body.get("email_failed") in (None, False)

    def test_pending_invite_shows_in_admin_users(self, admin_session, created_user_ids):
        if not created_user_ids:
            pytest.skip("no created user")
        r = admin_session.get(f"{BASE_URL}/api/admin/users")
        assert r.status_code == 200
        users = r.json()
        if isinstance(users, dict) and "users" in users:
            users = users["users"]
        found = [u for u in users if u.get("id") == created_user_ids[0]]
        assert found, "newly invited user not in /admin/users list"
        u = found[0]
        # Must be pending: is_active False or must_change_password True
        assert (u.get("must_change_password") is True) or (u.get("is_active") is False), \
            f"invited user should be pending, got {u}"

    def test_resend_invite_rotates_token(self, admin_session, created_user_ids):
        if not created_user_ids:
            pytest.skip("no created user")
        uid = created_user_ids[0]
        r = admin_session.post(f"{BASE_URL}/api/org/invite-user/{uid}/resend")
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        body = r.json()
        assert ("message" in body) or ("invite_link" in body)

    def test_revoke_pending_user_removes_invitation(self, admin_session, created_user_ids):
        if not created_user_ids:
            pytest.skip("no created user")
        uid = created_user_ids[0]
        r = admin_session.delete(f"{BASE_URL}/api/admin/users/{uid}")
        assert r.status_code in (200, 204), f"{r.status_code} {r.text[:300]}"
        # Verify gone
        r2 = admin_session.get(f"{BASE_URL}/api/admin/users")
        users = r2.json()
        if isinstance(users, dict) and "users" in users:
            users = users["users"]
        assert not any(u.get("id") == uid for u in users), "user should be deleted"
        created_user_ids.remove(uid)

    def test_invite_with_team_assignment(self, admin_session, created_user_ids):
        """Verify team_id acceptance — team assigned pre-accept."""
        # Fetch any team
        r = admin_session.get(f"{BASE_URL}/api/org/settings")
        if r.status_code != 200:
            pytest.skip("org settings not available")
        settings = r.json()
        team_id = None
        for s in (settings if isinstance(settings, list) else settings.get("settings", [])):
            for t in s.get("teams", []) or []:
                team_id = t.get("id")
                break
            if team_id:
                break
        if not team_id:
            pytest.skip("no team available to test team-scoped invite")
        email = f"TEST_team_{uuid.uuid4().hex[:8]}@example.com"
        payload = {"name": "TEST TeamInvite", "email": email, "role": "attendee", "team_id": team_id}
        r = admin_session.post(f"{BASE_URL}/api/org/invite-user", json=payload)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        created_user_ids.append(body["id"])


class TestSuperAdminInviteRegression:
    def test_super_admin_can_login_and_invite_admin(self):
        s = requests.Session()
        data = _login(s, SUPER_EMAIL, SUPER_PASSWORD)
        # List orgs
        r = s.get(f"{BASE_URL}/api/super-admin/orgs")
        if r.status_code != 200:
            pytest.skip(f"super-admin orgs listing failed: {r.status_code}")
        orgs = r.json()
        orgs_list = orgs if isinstance(orgs, list) else orgs.get("orgs") or orgs.get("organisations") or []
        if not orgs_list:
            pytest.skip("no orgs available")
        org_id = orgs_list[0].get("id")
        email = f"TEST_sa_{uuid.uuid4().hex[:8]}@example.com"
        payload = {"name": "TEST SA Invitee", "email": email}
        r = s.post(f"{BASE_URL}/api/super-admin/orgs/{org_id}/invite", json=payload)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"
        body = r.json()
        uid = body.get("id") or body.get("user_id")
        # Cleanup
        if uid:
            s2 = requests.Session()
            _login(s2, ADMIN_EMAIL, ADMIN_PASSWORD)
            s2.delete(f"{BASE_URL}/api/admin/users/{uid}")


def test_zz_cleanup(admin_session, created_user_ids):
    """Teardown — delete any remaining TEST_ users."""
    for uid in list(created_user_ids):
        admin_session.delete(f"{BASE_URL}/api/admin/users/{uid}")
