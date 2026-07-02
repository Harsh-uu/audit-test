"""
Tests for supervision document upload feature (doc_uploads router).
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

MANAGER_EMAIL = "manager@supervision.com"
MANAGER_PASS = "Manager123!"
STAFF_EMAIL = "staff@supervision.com"
STAFF_PASS = "Staff123!"

EXISTING_UPLOAD_ID = "6a46b912a09c5dcbd7140086"


@pytest.fixture(scope="module")
def manager_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": MANAGER_EMAIL, "password": MANAGER_PASS})
    assert r.status_code == 200, f"Manager login failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def staff_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": STAFF_EMAIL, "password": STAFF_PASS})
    assert r.status_code == 200, f"Staff login failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def manager_headers(manager_token):
    return {"Authorization": f"Bearer {manager_token}"}


@pytest.fixture(scope="module")
def staff_headers(staff_token):
    return {"Authorization": f"Bearer {staff_token}"}


class TestDocUploadsManagerAccess:
    """Manager can list and view doc uploads"""

    def test_list_uploads_as_manager(self, manager_headers):
        r = requests.get(f"{BASE_URL}/api/doc-uploads/", headers=manager_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        print(f"Found {len(data)} uploads")

    def test_get_existing_upload(self, manager_headers):
        r = requests.get(f"{BASE_URL}/api/doc-uploads/{EXISTING_UPLOAD_ID}", headers=manager_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == EXISTING_UPLOAD_ID
        assert data["status"] == "done"
        assert len(data["cqc_mappings"]) >= 1
        assert len(data["care_cert_mappings"]) >= 1
        assert "staff_name" in data
        assert "filename" in data
        assert "meeting_date" in data
        print(f"Upload: {data['label']}, CQC: {len(data['cqc_mappings'])}, CC: {len(data['care_cert_mappings'])}")

    def test_upload_document(self, manager_headers):
        """Upload a real DOCX and verify it returns processing status"""
        # Get staff list first
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=manager_headers)
        assert r.status_code == 200
        users = r.json()
        staff_users = [u for u in users if u["role"] not in ("admin", "manager", "super_admin")]
        assert len(staff_users) > 0, "No non-admin users found"
        staff_id = staff_users[0]["id"]

        with open("/tmp/test_supervision.docx", "rb") as f:
            files = {"file": ("test_supervision.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
            data = {"staff_id": staff_id, "label": "TEST_Doc Upload Jan 2025", "meeting_date": "2025-01-15"}
            r = requests.post(f"{BASE_URL}/api/doc-uploads/", headers=manager_headers, files=files, data=data)

        assert r.status_code == 200, f"Upload failed: {r.text}"
        result = r.json()
        assert result["status"] in ["processing", "done"]
        assert result["staff_id"] == staff_id
        assert result["label"] == "TEST_Doc Upload Jan 2025"
        assert result["meeting_date"] == "2025-01-15"
        print(f"Uploaded doc id: {result['id']}, status: {result['status']}")

        # Store for cleanup
        TestDocUploadsManagerAccess._created_id = result["id"]

    def test_delete_test_upload(self, manager_headers):
        """Cleanup the test upload"""
        upload_id = getattr(TestDocUploadsManagerAccess, "_created_id", None)
        if not upload_id:
            pytest.skip("No test upload created")
        r = requests.delete(f"{BASE_URL}/api/doc-uploads/{upload_id}", headers=manager_headers)
        assert r.status_code == 200
        # Verify it's gone
        r2 = requests.get(f"{BASE_URL}/api/doc-uploads/{upload_id}", headers=manager_headers)
        assert r2.status_code == 404


class TestDocUploadsStaffRestriction:
    """Staff cannot access doc uploads endpoints"""

    def test_staff_cannot_list_uploads(self, staff_headers):
        r = requests.get(f"{BASE_URL}/api/doc-uploads/", headers=staff_headers)
        assert r.status_code == 403

    def test_staff_cannot_get_upload(self, staff_headers):
        r = requests.get(f"{BASE_URL}/api/doc-uploads/{EXISTING_UPLOAD_ID}", headers=staff_headers)
        assert r.status_code == 403

    def test_staff_cannot_upload_doc(self, staff_headers):
        with open("/tmp/test_supervision.docx", "rb") as f:
            files = {"file": ("test.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
            data = {"staff_id": "someid", "label": "test", "meeting_date": "2025-01-01"}
            r = requests.post(f"{BASE_URL}/api/doc-uploads/", headers=staff_headers, files=files, data=data)
        assert r.status_code == 403


class TestDocUploadsPortfolio:
    """Staff portfolio shows uploaded documents"""

    def test_portfolio_includes_doc_uploads(self, manager_headers):
        """The list endpoint accepts staff_id filter"""
        r = requests.get(f"{BASE_URL}/api/doc-uploads/", headers=manager_headers)
        assert r.status_code == 200
        all_uploads = r.json()
        if all_uploads:
            staff_id = all_uploads[0]["staff_id"]
            r2 = requests.get(f"{BASE_URL}/api/doc-uploads/?staff_id={staff_id}", headers=manager_headers)
            assert r2.status_code == 200
            filtered = r2.json()
            assert all(u["staff_id"] == staff_id for u in filtered)
            print(f"staff_id filter works: {len(filtered)} uploads for staff {staff_id}")
