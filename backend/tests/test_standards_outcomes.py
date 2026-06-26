import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


def get_auth_token(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code == 200:
        data = r.json()
        return data.get("access_token") or data.get("token")
    return None


@pytest.fixture(scope="module")
def admin_token():
    token = get_auth_token("admin@supervision.com", "Admin123!")
    if not token:
        pytest.skip("Admin login failed")
    return token


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


class TestStandardsOutcomes:
    """Test Care Certificate standards with outcomes"""

    def test_standards_returns_200(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/standards", headers=auth_headers)
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:200]}"
        print("GET /api/admin/standards: 200 OK")

    def test_all_16_care_cert_standards_present(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/standards", headers=auth_headers)
        data = r.json()
        care_certs = [s for s in data if s.get("type") == "care_cert"]
        assert len(care_certs) == 16, f"Expected 16 care cert standards, got {len(care_certs)}"
        print(f"Found {len(care_certs)} care cert standards")

    def test_all_care_cert_standards_have_outcomes(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/standards", headers=auth_headers)
        data = r.json()
        care_certs = [s for s in data if s.get("type") == "care_cert"]
        missing = [s["reference"] for s in care_certs if not s.get("outcomes")]
        assert len(missing) == 0, f"Standards missing outcomes: {missing}"
        print("All care cert standards have outcomes")

    def test_standard_2_has_3_outcomes(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/standards", headers=auth_headers)
        data = r.json()
        std2 = next((s for s in data if s.get("reference") == "Standard 2"), None)
        assert std2 is not None, "Standard 2 not found"
        outcomes = std2.get("outcomes", [])
        assert len(outcomes) == 3, f"Expected 3 outcomes for Standard 2, got {len(outcomes)}"
        refs = [o["ref"] for o in outcomes]
        assert "2.1" in refs and "2.2" in refs and "2.3" in refs, f"Unexpected refs: {refs}"
        print(f"Standard 2 outcomes: {refs}")

    def test_standard_6_has_7_outcomes(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/standards", headers=auth_headers)
        data = r.json()
        std6 = next((s for s in data if s.get("reference") == "Standard 6"), None)
        assert std6 is not None, "Standard 6 not found"
        outcomes = std6.get("outcomes", [])
        assert len(outcomes) == 7, f"Expected 7 outcomes for Standard 6, got {len(outcomes)}"
        print(f"Standard 6 outcomes count: {len(outcomes)}")

    def test_standard_13_has_7_outcomes(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/standards", headers=auth_headers)
        data = r.json()
        std13 = next((s for s in data if s.get("reference") == "Standard 13"), None)
        assert std13 is not None, "Standard 13 not found"
        outcomes = std13.get("outcomes", [])
        assert len(outcomes) == 7, f"Expected 7 outcomes for Standard 13, got {len(outcomes)}"
        print(f"Standard 13 outcomes count: {len(outcomes)}")

    def test_outcomes_have_ref_and_name_fields(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/standards", headers=auth_headers)
        data = r.json()
        care_certs = [s for s in data if s.get("type") == "care_cert"]
        for std in care_certs:
            for o in std.get("outcomes", []):
                assert "ref" in o, f"Outcome missing 'ref' in {std['reference']}: {o}"
                assert "name" in o, f"Outcome missing 'name' in {std['reference']}: {o}"
        print("All outcomes have ref and name fields")
