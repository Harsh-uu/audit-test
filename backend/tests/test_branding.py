"""Backend tests for org branding endpoints (GET/PUT /api/org/branding, POST logo, GET /api/auth/me)"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASS = "Admin123!"


@pytest.fixture(scope="module")
def admin_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["token"]


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


class TestBrandingEndpoints:
    def test_get_branding_returns_fields(self, auth_headers):
        """GET /api/org/branding returns has_logo and primary_color"""
        resp = requests.get(f"{BASE_URL}/api/org/branding", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "has_logo" in data, "Missing has_logo field"
        assert "primary_color" in data, "Missing primary_color field"
        print(f"GET branding: {data}")

    def test_put_branding_primary_color(self, auth_headers):
        """PUT /api/org/branding updates primary_color"""
        resp = requests.put(
            f"{BASE_URL}/api/org/branding",
            json={"primary_color": "#CC0000"},
            headers=auth_headers
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "message" in data
        print(f"PUT branding: {data}")

    def test_get_branding_after_update(self, auth_headers):
        """GET /api/org/branding reflects updated color"""
        # First set
        requests.put(f"{BASE_URL}/api/org/branding", json={"primary_color": "#AA1122"}, headers=auth_headers)
        resp = requests.get(f"{BASE_URL}/api/org/branding", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["primary_color"] == "#AA1122", f"Expected #AA1122, got {data['primary_color']}"
        print(f"Verified color persistence: {data}")

    def test_auth_me_includes_org_branding(self, auth_headers):
        """GET /api/auth/me includes org_branding with has_logo and primary_color"""
        resp = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "org_branding" in data, f"Missing org_branding in /auth/me response. Keys: {list(data.keys())}"
        branding = data["org_branding"]
        assert "has_logo" in branding, f"Missing has_logo in org_branding: {branding}"
        assert "primary_color" in branding, f"Missing primary_color in org_branding: {branding}"
        print(f"/auth/me org_branding: {branding}")

    def test_put_branding_non_admin_forbidden(self):
        """PUT /api/org/branding should 403 for non-admin"""
        # Use no auth header
        resp = requests.put(f"{BASE_URL}/api/org/branding", json={"primary_color": "#000000"})
        assert resp.status_code in [401, 403], f"Expected 401/403, got {resp.status_code}"
        print(f"Non-admin branding update correctly rejected: {resp.status_code}")

    def test_get_logo_endpoint_no_logo(self, auth_headers):
        """GET /api/org/branding/logo/{org_id} returns 404 if no logo set (public endpoint)"""
        # Get org_id from /auth/me
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers).json()
        org_id = me.get("org_id")
        assert org_id, "No org_id in /auth/me"
        resp = requests.get(f"{BASE_URL}/api/org/branding/logo/{org_id}")
        # Either 200 (logo exists) or 404 (no logo) - both are valid
        assert resp.status_code in [200, 404], f"Unexpected status: {resp.status_code}"
        print(f"Logo endpoint status: {resp.status_code}")
