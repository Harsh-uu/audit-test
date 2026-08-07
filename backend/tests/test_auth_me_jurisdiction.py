"""
Tests for:
1. /api/auth/me returns org_jurisdiction and org_service_type
2. Login flow works (regression test for auth.py changes)
3. Team insights returns org_jurisdiction and org_service_type
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASS = "Admin123!"
MANAGER_EMAIL = "manager@supervision.com"
MANAGER_PASS = "Manager123!"


def get_token(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        data = r.json()
        return data.get("access_token") or data.get("token")
    return None


class TestLoginRegression:
    """Verify login still works after auth.py changes"""

    def test_admin_login_success(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}
        )
        assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
        data = r.json()
        token = data.get("access_token") or data.get("token")
        assert token, f"No token in login response: {data}"
        print(f"PASS: Admin login OK - token present")

    def test_manager_login_success(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": MANAGER_EMAIL, "password": MANAGER_PASS}
        )
        assert r.status_code == 200, f"Manager login failed: {r.status_code} {r.text}"
        data = r.json()
        token = data.get("access_token") or data.get("token")
        assert token, f"No token in manager login response: {data}"
        print(f"PASS: Manager login OK - token present")

    def test_invalid_credentials_rejected(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": "WrongPassword999!"}
        )
        assert r.status_code in [401, 403, 400], f"Expected auth error, got {r.status_code}"
        print(f"PASS: Invalid credentials correctly rejected with {r.status_code}")


class TestAuthMeJurisdiction:
    """Verify /api/auth/me returns org_jurisdiction and org_service_type"""

    def test_me_returns_org_jurisdiction_for_admin(self):
        token = get_token(ADMIN_EMAIL, ADMIN_PASS)
        assert token, "Could not get admin token"
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200, f"/api/auth/me failed: {r.status_code} {r.text}"
        data = r.json()
        assert "org_jurisdiction" in data, f"org_jurisdiction missing from /me response. Keys: {list(data.keys())}"
        jurisdiction = data["org_jurisdiction"]
        assert isinstance(jurisdiction, str), f"org_jurisdiction should be string, got {type(jurisdiction)}"
        assert len(jurisdiction) > 0, "org_jurisdiction should not be empty"
        print(f"PASS: org_jurisdiction = '{jurisdiction}'")

    def test_me_returns_org_service_type_for_admin(self):
        token = get_token(ADMIN_EMAIL, ADMIN_PASS)
        assert token, "Could not get admin token"
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200, f"/api/auth/me failed: {r.status_code} {r.text}"
        data = r.json()
        assert "org_service_type" in data, f"org_service_type missing from /me response. Keys: {list(data.keys())}"
        service_type = data["org_service_type"]
        assert service_type is not None, "org_service_type should not be None (empty string is OK)"
        print(f"PASS: org_service_type = '{service_type}'")

    def test_me_jurisdiction_is_england_for_test_company(self):
        """Test Company org should have jurisdiction='england'"""
        token = get_token(ADMIN_EMAIL, ADMIN_PASS)
        assert token, "Could not get admin token"
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200, f"/api/auth/me failed"
        data = r.json()
        jurisdiction = data.get("org_jurisdiction", "")
        # Test Company org should be 'england'
        assert jurisdiction == "england", f"Expected 'england' for Test Company, got '{jurisdiction}'"
        print(f"PASS: Test Company org_jurisdiction = 'england' as expected")

    def test_me_returns_correct_org_name(self):
        """Also verify org_name still returned (regression check)"""
        token = get_token(ADMIN_EMAIL, ADMIN_PASS)
        assert token, "Could not get admin token"
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200
        data = r.json()
        assert "org_name" in data, f"org_name missing from /me response. Keys: {list(data.keys())}"
        print(f"PASS: org_name = '{data['org_name']}'")

    def test_me_no_sensitive_fields(self):
        """Verify password hash and MFA fields not leaked"""
        token = get_token(ADMIN_EMAIL, ADMIN_PASS)
        assert token, "Could not get admin token"
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200
        data = r.json()
        assert "password_hash" not in data, "password_hash should NOT be in /me response!"
        assert "mfa_code" not in data, "mfa_code should NOT be in /me response!"
        print("PASS: No sensitive fields leaked in /me response")

    def test_me_requires_auth(self):
        """Unauthenticated request to /me should return 401"""
        r = requests.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401, f"Expected 401 without auth, got {r.status_code}"
        print(f"PASS: /me correctly requires authentication (401 returned)")

    def test_me_returns_jurisdiction_for_manager(self):
        """Manager in same org should also get org_jurisdiction"""
        token = get_token(MANAGER_EMAIL, MANAGER_PASS)
        assert token, "Could not get manager token"
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200, f"/api/auth/me failed for manager: {r.text}"
        data = r.json()
        assert "org_jurisdiction" in data, "org_jurisdiction missing for manager"
        assert "org_service_type" in data, "org_service_type missing for manager"
        print(f"PASS: Manager also gets org_jurisdiction='{data['org_jurisdiction']}'")


class TestTeamInsightsJurisdiction:
    """Verify team-insights endpoint includes org_jurisdiction and org_service_type"""

    def test_team_insights_includes_jurisdiction(self):
        token = get_token(ADMIN_EMAIL, ADMIN_PASS)
        assert token, "Could not get admin token"
        r = requests.get(
            f"{BASE_URL}/api/admin/team-insights",
            headers={"Authorization": f"Bearer {token}"}
        )
        # May return 200 even if no data
        assert r.status_code == 200, f"team-insights failed: {r.status_code} {r.text}"
        data = r.json()
        assert "org_jurisdiction" in data, f"org_jurisdiction missing from team-insights. Keys: {list(data.keys())}"
        assert "org_service_type" in data, f"org_service_type missing from team-insights. Keys: {list(data.keys())}"
        jurisdiction = data["org_jurisdiction"]
        assert isinstance(jurisdiction, str), f"org_jurisdiction should be string"
        print(f"PASS: team-insights org_jurisdiction='{jurisdiction}', org_service_type='{data['org_service_type']}'")

    def test_team_insights_jurisdiction_matches_me(self):
        """org_jurisdiction in team-insights should match /me endpoint"""
        token = get_token(ADMIN_EMAIL, ADMIN_PASS)
        assert token, "Could not get admin token"

        me_r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        insights_r = requests.get(f"{BASE_URL}/api/admin/team-insights", headers={"Authorization": f"Bearer {token}"})

        assert me_r.status_code == 200
        assert insights_r.status_code == 200

        me_jurisdiction = me_r.json().get("org_jurisdiction")
        insights_jurisdiction = insights_r.json().get("org_jurisdiction")

        assert me_jurisdiction == insights_jurisdiction, \
            f"Jurisdiction mismatch: /me='{me_jurisdiction}', team-insights='{insights_jurisdiction}'"
        print(f"PASS: jurisdiction consistent: /me='{me_jurisdiction}' == team-insights='{insights_jurisdiction}'")
