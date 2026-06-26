"""Tests for Staff Portfolio and Admin Evidence Export features"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASS = "Admin123!"
STAFF_EMAIL = "staff@supervision.com"
STAFF_PASS = "Staff123!"

ADMIN_ID = "6a3e5727bb3b2159b3c93f61"
STAFF_ID = "6a3e5728bb3b2159b3c93f63"
MEETING_ID = "6a3e6204373ddc91df1947cf"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def staff_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": STAFF_EMAIL, "password": STAFF_PASS})
    assert r.status_code == 200, f"Staff login failed: {r.text}"
    return r.json()["token"]


class TestPortfolioEndpoint:
    """GET /api/portfolio/{user_id}"""

    def test_admin_can_view_staff_portfolio(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/portfolio/{STAFF_ID}", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        data = r.json()
        assert "user" in data
        assert "stats" in data
        assert "cqc_summary" in data
        assert "care_cert_summary" in data
        assert "custom_summary" in data
        assert "meetings" in data

    def test_portfolio_stats_structure(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/portfolio/{STAFF_ID}", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        stats = r.json()["stats"]
        assert "total_meetings" in stats
        assert "cqc_count" in stats
        assert "care_cert_count" in stats
        assert "custom_count" in stats
        assert stats["total_meetings"] >= 1

    def test_portfolio_has_meetings_data(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/portfolio/{STAFF_ID}", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        meetings = r.json()["meetings"]
        assert len(meetings) >= 1
        m = meetings[0]
        assert "id" in m
        assert "title" in m
        assert "cqc_count" in m

    def test_staff_can_view_own_portfolio(self, staff_token):
        r = requests.get(f"{BASE_URL}/api/portfolio/{STAFF_ID}", headers={"Authorization": f"Bearer {staff_token}"})
        assert r.status_code == 200

    def test_staff_cannot_view_other_portfolio(self, staff_token):
        # Staff trying to view admin portfolio -> 403
        r = requests.get(f"{BASE_URL}/api/portfolio/{ADMIN_ID}", headers={"Authorization": f"Bearer {staff_token}"})
        assert r.status_code == 403

    def test_portfolio_404_for_invalid_user(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/portfolio/000000000000000000000000", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 404


class TestPortfolioPdfExport:
    """GET /api/portfolio/{user_id}/export-pdf"""

    def test_admin_can_export_pdf(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/portfolio/{STAFF_ID}/export-pdf", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert len(r.content) > 1000  # PDF has content

    def test_staff_cannot_export_other_pdf(self, staff_token):
        r = requests.get(f"{BASE_URL}/api/portfolio/{ADMIN_ID}/export-pdf", headers={"Authorization": f"Bearer {staff_token}"})
        assert r.status_code == 403


class TestAdminMeetingsBrief:
    """GET /api/admin/meetings-brief"""

    def test_returns_meetings_list(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/meetings-brief", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        if data:
            m = data[0]
            assert "id" in m
            assert "title" in m


class TestAdminExportEvidence:
    """POST /api/admin/export-evidence"""

    def test_csv_export(self, admin_token):
        payload = {"user_ids": [STAFF_ID], "meeting_ids": [MEETING_ID], "format": "csv"}
        r = requests.post(f"{BASE_URL}/api/admin/export-evidence", json=payload, headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "") or "application/octet-stream" in r.headers.get("content-type", "")

    def test_pdf_export(self, admin_token):
        payload = {"user_ids": [STAFF_ID], "meeting_ids": [MEETING_ID], "format": "pdf"}
        r = requests.post(f"{BASE_URL}/api/admin/export-evidence", json=payload, headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200

    def test_non_admin_cannot_export(self, staff_token):
        payload = {"user_ids": [STAFF_ID], "meeting_ids": [MEETING_ID], "format": "csv"}
        r = requests.post(f"{BASE_URL}/api/admin/export-evidence", json=payload, headers={"Authorization": f"Bearer {staff_token}"})
        assert r.status_code in [403, 401]
