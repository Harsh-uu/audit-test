"""Tests for org-wide speaker_colors in Branding (PUT/GET /api/org/branding + /auth/me)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback to frontend/.env
    with open("/app/frontend/.env") as fh:
        for line in fh:
            if line.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASSWORD = "Admin123!X"


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    body = r.json()
    if body.get("requires_mfa"):
        pytest.skip("Admin login unexpectedly required MFA")
    return s


class TestBrandingSpeakerColors:
    def test_get_branding_returns_speaker_colors_field(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/org/branding")
        assert r.status_code == 200
        data = r.json()
        assert "speaker_colors" in data
        assert isinstance(data["speaker_colors"], dict)

    def test_put_branding_persists_speaker_colors(self, admin_session):
        payload = {
            "primary_color": "#1E3A8A",
            "speaker_colors": {
                "manager": "#93C5FD",
                "attendees": ["#FCA5A5", "#86EFAC", "#FDE047", "#D8B4FE"],
            },
        }
        r = admin_session.put(f"{BASE_URL}/api/org/branding", json=payload)
        assert r.status_code == 200, r.text

        r2 = admin_session.get(f"{BASE_URL}/api/org/branding")
        assert r2.status_code == 200
        sc = r2.json().get("speaker_colors") or {}
        assert sc.get("manager") == "#93C5FD"
        assert sc.get("attendees") == ["#FCA5A5", "#86EFAC", "#FDE047", "#D8B4FE"]

    def test_put_branding_updates_speaker_colors(self, admin_session):
        # Change values and verify round-trip
        new_payload = {
            "speaker_colors": {
                "manager": "#A5B4FC",
                "attendees": ["#FDBA74", "#BEF264", "#5EEAD4", "#F9A8D4"],
            }
        }
        r = admin_session.put(f"{BASE_URL}/api/org/branding", json=new_payload)
        assert r.status_code == 200

        r2 = admin_session.get(f"{BASE_URL}/api/org/branding")
        sc = r2.json().get("speaker_colors") or {}
        assert sc.get("manager") == "#A5B4FC"
        assert sc.get("attendees") == ["#FDBA74", "#BEF264", "#5EEAD4", "#F9A8D4"]

        # Restore back to original expected fixture per test_credentials doc
        restore = {"speaker_colors": {
            "manager": "#93C5FD",
            "attendees": ["#FCA5A5", "#86EFAC", "#FDE047", "#D8B4FE"],
        }}
        admin_session.put(f"{BASE_URL}/api/org/branding", json=restore)

    def test_auth_me_exposes_speaker_colors(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200
        me = r.json()
        # org_branding should exist and include speaker_colors
        assert "org_branding" in me, f"auth/me missing org_branding: {me.keys()}"
        ob = me["org_branding"] or {}
        assert "speaker_colors" in ob, f"org_branding missing speaker_colors: {ob}"
        sc = ob["speaker_colors"] or {}
        assert sc.get("manager") == "#93C5FD"
        assert sc.get("attendees") == ["#FCA5A5", "#86EFAC", "#FDE047", "#D8B4FE"]

    def test_branding_primary_color_still_persists(self, admin_session):
        """Regression: ensure primary_color still works alongside speaker_colors."""
        r = admin_session.put(f"{BASE_URL}/api/org/branding", json={"primary_color": "#1E3A8A"})
        assert r.status_code == 200
        r2 = admin_session.get(f"{BASE_URL}/api/org/branding")
        assert r2.json().get("primary_color") == "#1E3A8A"


class TestBrandingRBAC:
    def test_attendee_cannot_put_branding(self):
        s = requests.Session()
        # Try with attendee account
        r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "user@supervision.com", "password": "Staff123!"})
        if r.status_code != 200 or r.json().get("requires_mfa"):
            pytest.skip("Attendee login unavailable")
        put_r = s.put(f"{BASE_URL}/api/org/branding", json={"speaker_colors": {"manager": "#000000", "attendees": ["#111111"]*4}})
        assert put_r.status_code == 403

    def test_attendee_can_get_branding(self):
        s = requests.Session()
        r = s.post(f"{BASE_URL}/api/auth/login", json={"email": "user@supervision.com", "password": "Staff123!"})
        if r.status_code != 200 or r.json().get("requires_mfa"):
            pytest.skip("Attendee login unavailable")
        get_r = s.get(f"{BASE_URL}/api/org/branding")
        assert get_r.status_code == 200
        assert "speaker_colors" in get_r.json()
