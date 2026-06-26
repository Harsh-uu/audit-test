"""Backend tests for Team Intelligence / team-insights endpoint"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@supervision.com", "password": "Admin123!"})
    assert r.status_code == 200
    return r.cookies

@pytest.fixture(scope="module")
def staff_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "staff@supervision.com", "password": "Staff123!"})
    assert r.status_code == 200
    return r.cookies

class TestTeamInsights:
    """Tests for GET /api/admin/team-insights"""

    def test_admin_can_access(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights", cookies=admin_token)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"

    def test_response_shape(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights", cookies=admin_token)
        data = r.json()
        assert "staff_count" in data
        assert "meeting_count" in data
        assert "matrix" in data
        assert "themes" in data

    def test_staff_count(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights", cookies=admin_token)
        data = r.json()
        assert data["staff_count"] >= 1

    def test_cqc_standards_count(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights", cookies=admin_token)
        data = r.json()
        cqc_stds = data["matrix"]["cqc"]["standards"]
        assert len(cqc_stds) == 14, f"Expected 14 CQC standards, got {len(cqc_stds)}"

    def test_care_cert_standards_count(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights", cookies=admin_token)
        data = r.json()
        cc_stds = data["matrix"]["care_cert"]["standards"]
        assert len(cc_stds) == 16, f"Expected 16 Care Cert standards, got {len(cc_stds)}"

    def test_matrix_rows_present(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights", cookies=admin_token)
        data = r.json()
        cqc_rows = data["matrix"]["cqc"]["rows"]
        assert len(cqc_rows) >= 1, "Expected at least 1 row in CQC matrix"

    def test_matrix_cells_have_status(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights", cookies=admin_token)
        data = r.json()
        row = data["matrix"]["cqc"]["rows"][0]
        assert "cells" in row
        for ref, cell in row["cells"].items():
            assert "status" in cell
            assert cell["status"] in ["evidenced", "needs_review", "gap"]

    def test_themes_coverage_gaps(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights", cookies=admin_token)
        data = r.json()
        assert "coverage_gaps" in data["themes"]
        assert isinstance(data["themes"]["coverage_gaps"], list)

    def test_themes_common_risks(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights", cookies=admin_token)
        data = r.json()
        assert "common_risks" in data["themes"]

    def test_themes_outstanding_actions(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights", cookies=admin_token)
        data = r.json()
        assert "outstanding_actions" in data["themes"]

    def test_staff_user_gets_403(self, staff_token):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights", cookies=staff_token)
        assert r.status_code == 403, f"Expected 403 for staff, got {r.status_code}"

    def test_unauthenticated_gets_401_or_403(self):
        r = requests.get(f"{BASE_URL}/api/admin/team-insights")
        assert r.status_code in [401, 403], f"Expected 401/403, got {r.status_code}"
