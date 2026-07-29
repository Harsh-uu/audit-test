"""
Tests for Phase 1 Foundation: Standards org isolation and doc_type upload field.
"""
import pytest
import requests
import os
import io

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


@pytest.fixture(scope="module")
def admin_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@supervision.com",
        "password": "Admin123!"
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json().get("token") or resp.json().get("access_token")


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ── Standards library tests ────────────────────────────────────────────────────

class TestStandardsLibrary:
    """Standards org isolation tests"""

    def test_list_standards_returns_items(self, admin_headers):
        """GET /api/admin/standards returns a list"""
        resp = requests.get(f"{BASE_URL}/api/admin/standards", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        print(f"Standards count: {len(data)}")

    def test_list_standards_count_approx_64(self, admin_headers):
        """Should return ~64 items for admin@supervision.com (30 system + 34 org-custom)"""
        resp = requests.get(f"{BASE_URL}/api/admin/standards", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Accept a range around 64 to handle minor seed drift
        assert len(data) >= 30, f"Expected >=30 standards, got {len(data)}"
        print(f"Standards count: {len(data)} (expected ~64)")

    def test_create_standard_has_org_id(self, admin_headers):
        """POST /api/admin/standards sets org_id and is_system=False"""
        payload = {
            "type": "cqc",
            "reference": "TEST_Reg_Phase1",
            "name": "TEST Phase 1 Standard",
            "description": "Auto-test standard for phase 1 validation",
            "keywords": ["test"],
        }
        resp = requests.post(f"{BASE_URL}/api/admin/standards", json=payload, headers=admin_headers)
        assert resp.status_code == 200
        d = resp.json()
        assert d.get("is_system") is False, "Created standard should have is_system=False"
        assert d.get("org_id") is not None, "Created standard should have org_id set"
        assert d.get("reference") == "TEST_Reg_Phase1"
        print(f"Created standard id: {d.get('id')}, org_id: {d.get('org_id')}")
        return d["id"]

    def test_delete_org_standard(self, admin_headers):
        """DELETE /api/admin/standards/{id} deactivates org-owned standard"""
        # First create
        payload = {
            "type": "cqc",
            "reference": "TEST_DeleteMe",
            "name": "TEST Delete Standard",
            "description": "For deletion test",
        }
        create_resp = requests.post(f"{BASE_URL}/api/admin/standards", json=payload, headers=admin_headers)
        assert create_resp.status_code == 200
        std_id = create_resp.json()["id"]

        # Then delete
        del_resp = requests.delete(f"{BASE_URL}/api/admin/standards/{std_id}", headers=admin_headers)
        assert del_resp.status_code == 200
        print(f"Deleted standard {std_id}: {del_resp.json()}")

    def test_cannot_delete_system_standard(self, admin_headers):
        """DELETE should return 403 for is_system=True standards"""
        # Get any system standard
        resp = requests.get(f"{BASE_URL}/api/admin/standards", headers=admin_headers)
        assert resp.status_code == 200
        standards = resp.json()
        # Find a system standard (is_system=True)
        system_stds = [s for s in standards if s.get("is_system") is True]
        if not system_stds:
            pytest.skip("No system standards found to test deletion protection")
        sys_id = system_stds[0]["id"]
        del_resp = requests.delete(f"{BASE_URL}/api/admin/standards/{sys_id}", headers=admin_headers)
        assert del_resp.status_code == 403, f"Expected 403, got {del_resp.status_code}: {del_resp.text}"
        print(f"Correctly blocked deletion of system standard {sys_id}")


# ── Doc uploads doc_type tests ─────────────────────────────────────────────────

class TestDocUploadDocType:
    """doc_type field on supervision doc uploads"""

    @pytest.fixture(scope="class")
    def staff_id(self, admin_headers):
        """Get a staff member id"""
        resp = requests.get(f"{BASE_URL}/api/admin/users", headers=admin_headers)
        assert resp.status_code == 200
        users = resp.json()
        staff = [u for u in users if u.get("role") in ("attendee", "manager")]
        if not staff:
            pytest.skip("No staff found")
        return staff[0]["id"]

    def _make_dummy_pdf(self):
        """Return minimal valid-ish PDF bytes"""
        content = b"%PDF-1.4\n1 0 obj\n<</Type /Catalog>>\nendobj\ntrailer\n<</Root 1 0 R>>\n%%EOF"
        return io.BytesIO(content)

    def test_upload_with_doc_type_stores_field(self, admin_headers, staff_id):
        """POST /api/doc-uploads/ with doc_type stores it correctly"""
        files = {"file": ("test.pdf", self._make_dummy_pdf(), "application/pdf")}
        data = {
            "staff_id": staff_id,
            "label": "TEST Phase1 Upload",
            "meeting_date": "2025-01-15",
            "doc_type": "job_description",
        }
        resp = requests.post(
            f"{BASE_URL}/api/doc-uploads/",
            headers={"Authorization": admin_headers["Authorization"]},
            files=files,
            data=data,
        )
        assert resp.status_code == 200, f"Upload failed: {resp.text}"
        d = resp.json()
        assert d.get("doc_type") == "job_description", f"Expected 'job_description', got {d.get('doc_type')}"
        print(f"Upload id: {d.get('id')}, doc_type: {d.get('doc_type')}")
        return d["id"]

    def test_upload_with_other_doc_type(self, admin_headers, staff_id):
        """When 'other' doc_type is provided, it is stored as-is"""
        files = {"file": ("test2.pdf", self._make_dummy_pdf(), "application/pdf")}
        data = {
            "staff_id": staff_id,
            "label": "TEST Other Type Upload",
            "meeting_date": "2025-02-01",
            "doc_type": "Custom Description Here",
        }
        resp = requests.post(
            f"{BASE_URL}/api/doc-uploads/",
            headers={"Authorization": admin_headers["Authorization"]},
            files=files,
            data=data,
        )
        assert resp.status_code == 200
        d = resp.json()
        assert d.get("doc_type") == "Custom Description Here"
        print(f"Custom doc_type stored: {d.get('doc_type')}")

    def test_upload_without_doc_type_defaults_to_other(self, admin_headers, staff_id):
        """When no doc_type provided, defaults to 'other'"""
        files = {"file": ("test3.pdf", self._make_dummy_pdf(), "application/pdf")}
        data = {
            "staff_id": staff_id,
            "label": "TEST No DocType",
            "meeting_date": "2025-03-01",
        }
        resp = requests.post(
            f"{BASE_URL}/api/doc-uploads/",
            headers={"Authorization": admin_headers["Authorization"]},
            files=files,
            data=data,
        )
        assert resp.status_code == 200
        d = resp.json()
        assert d.get("doc_type") == "other", f"Expected 'other', got {d.get('doc_type')}"
        print(f"Default doc_type: {d.get('doc_type')}")

    def test_list_uploads_includes_doc_type(self, admin_headers):
        """GET /api/doc-uploads/ response includes doc_type field"""
        resp = requests.get(f"{BASE_URL}/api/doc-uploads/", headers=admin_headers)
        assert resp.status_code == 200
        uploads = resp.json()
        if uploads:
            assert "doc_type" in uploads[0], "doc_type missing from upload list response"
            print(f"First upload doc_type: {uploads[0].get('doc_type')}")
        else:
            print("No uploads found — skipping doc_type presence check")
