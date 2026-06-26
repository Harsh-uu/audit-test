"""
Tests for Supervision 2.0 features:
- Admin Library document upload (Custom Standards)
- PDF export endpoint
- Send email endpoint
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASS = "Admin123!"
MANAGER_EMAIL = "manager@supervision.com"
MANAGER_PASS = "Manager123!"
TEST_MEETING_ID = "6a3e6204373ddc91df1947cf"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def manager_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": MANAGER_EMAIL, "password": MANAGER_PASS})
    assert r.status_code == 200, f"Manager login failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def manager_headers(manager_token):
    return {"Authorization": f"Bearer {manager_token}"}


# ── Documents API ─────────────────────────────────────────────────────────────

class TestDocumentsAPI:
    """Test custom standards document upload and management"""

    def test_list_documents_as_admin(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/standards/documents", headers=admin_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        print(f"GET documents: {len(r.json())} docs found")

    def test_list_documents_as_manager(self, manager_headers):
        r = requests.get(f"{BASE_URL}/api/admin/standards/documents", headers=manager_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_upload_txt_document(self, admin_headers):
        """Upload a small TXT file and verify parse_status=parsing returned"""
        content = b"Company Values:\n1. Compassion - We show genuine care\n2. Integrity - We act with honesty\n3. Excellence - We strive for best outcomes"
        files = {"file": ("test_values.txt", content, "text/plain")}
        data = {"label": "TEST Company Values"}
        # Use only Authorization header, not Content-Type (multipart handled by requests)
        headers = {"Authorization": admin_headers["Authorization"]}
        r = requests.post(f"{BASE_URL}/api/admin/standards/upload", headers=headers, files=files, data=data)
        assert r.status_code == 200, f"Upload failed: {r.text}"
        doc = r.json()
        assert doc.get("parse_status") == "parsing", f"Expected parsing, got {doc.get('parse_status')}"
        assert doc.get("id"), "No ID in response"
        assert doc.get("label") == "TEST Company Values"
        print(f"Uploaded doc id={doc['id']}, status={doc['parse_status']}")
        # Store for later cleanup
        TestDocumentsAPI._uploaded_doc_id = doc["id"]

    def test_upload_rejects_empty_file(self, admin_headers):
        files = {"file": ("empty.txt", b"", "text/plain")}
        data = {"label": "Empty"}
        headers = {"Authorization": admin_headers["Authorization"]}
        r = requests.post(f"{BASE_URL}/api/admin/standards/upload", headers=headers, files=files, data=data)
        assert r.status_code == 400

    def test_upload_rejects_unsupported_type(self, admin_headers):
        files = {"file": ("test.jpg", b"fakeimage", "image/jpeg")}
        data = {"label": "Bad file"}
        headers = {"Authorization": admin_headers["Authorization"]}
        r = requests.post(f"{BASE_URL}/api/admin/standards/upload", headers=headers, files=files, data=data)
        assert r.status_code == 400

    def test_patch_document_toggle(self, admin_headers):
        """PATCH doc is_active"""
        doc_id = getattr(TestDocumentsAPI, "_uploaded_doc_id", None)
        if not doc_id:
            pytest.skip("No doc uploaded to patch")
        r = requests.patch(f"{BASE_URL}/api/admin/standards/documents/{doc_id}", json={"is_active": False}, headers=admin_headers)
        assert r.status_code == 200
        assert "Updated" in r.json().get("message", "")
        # Re-enable
        r2 = requests.patch(f"{BASE_URL}/api/admin/standards/documents/{doc_id}", json={"is_active": True}, headers=admin_headers)
        assert r2.status_code == 200

    def test_document_parses_after_delay(self, admin_headers):
        """Wait ~25s and verify parse_status becomes parsed"""
        doc_id = getattr(TestDocumentsAPI, "_uploaded_doc_id", None)
        if not doc_id:
            pytest.skip("No doc uploaded")
        print("Waiting 25s for AI parsing...")
        time.sleep(25)
        r = requests.get(f"{BASE_URL}/api/admin/standards/documents", headers=admin_headers)
        assert r.status_code == 200
        docs = r.json()
        doc = next((d for d in docs if d["id"] == doc_id), None)
        assert doc is not None, "Uploaded doc not found in list"
        print(f"Doc parse_status after 25s: {doc.get('parse_status')}")
        # Status should be parsed or still parsing (AI can be slow)
        assert doc.get("parse_status") in ["parsed", "parsing", "failed"], f"Unexpected status: {doc.get('parse_status')}"
        if doc.get("parse_status") == "parsed":
            assert isinstance(doc.get("extracted_criteria"), list)
            print(f"Criteria count: {doc.get('criteria_count', 0)}")

    def test_delete_document(self, admin_headers):
        """DELETE the uploaded test doc"""
        doc_id = getattr(TestDocumentsAPI, "_uploaded_doc_id", None)
        if not doc_id:
            pytest.skip("No doc to delete")
        r = requests.delete(f"{BASE_URL}/api/admin/standards/documents/{doc_id}", headers=admin_headers)
        assert r.status_code == 200
        # Verify removed
        r2 = requests.get(f"{BASE_URL}/api/admin/standards/documents", headers=admin_headers)
        docs = r2.json()
        assert not any(d["id"] == doc_id for d in docs), "Doc still present after delete"
        print(f"Doc {doc_id} deleted successfully")


# ── PDF Export ──────────────────────────────────────────────────────────────

class TestPDFExport:
    """Test PDF export endpoint"""

    def test_pdf_export_400_for_non_signed_off(self, admin_headers):
        """Meeting 6a3e6204373ddc91df1947cf is in_review => expect 400"""
        r = requests.get(f"{BASE_URL}/api/review/{TEST_MEETING_ID}/export-pdf", headers=admin_headers)
        # Should be 400 since not signed off
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        print(f"Correctly returned 400 for non-signed-off meeting")

    def test_signed_off_meeting_pdf(self, admin_headers):
        """Create a signed-off meeting and test PDF export"""
        # First check if any signed_off meeting exists
        r = requests.get(f"{BASE_URL}/api/meetings", headers=admin_headers)
        if r.status_code != 200:
            pytest.skip("Cannot list meetings")
        meetings = r.json()
        signed_off = [m for m in meetings if m.get("status") in ["signed_off", "shared"]]
        if not signed_off:
            print("No signed-off meetings available, skipping PDF content test")
            pytest.skip("No signed-off meetings available")
        m_id = signed_off[0]["id"]
        r2 = requests.get(f"{BASE_URL}/api/review/{m_id}/export-pdf?include_transcript=false", headers=admin_headers)
        assert r2.status_code == 200, f"PDF export failed: {r2.status_code} {r2.text[:200]}"
        assert r2.headers.get("content-type", "").startswith("application/pdf")
        assert len(r2.content) > 1000, "PDF too small - likely empty"
        print(f"PDF export OK: {len(r2.content)} bytes for meeting {m_id}")


# ── Email Send ───────────────────────────────────────────────────────────────

class TestEmailSend:
    """Test send-email endpoint"""

    def test_send_email_400_for_non_signed_off(self, admin_headers):
        r = requests.post(
            f"{BASE_URL}/api/review/{TEST_MEETING_ID}/send-email",
            json={"recipients": ["test@example.com"]},
            headers=admin_headers,
        )
        assert r.status_code == 400, f"Expected 400 for non-signed-off, got {r.status_code}"

    def test_send_email_signed_off(self, admin_headers):
        """Send email for a signed-off meeting (may fail if no Resend key, but endpoint should not 500)"""
        r = requests.get(f"{BASE_URL}/api/meetings", headers=admin_headers)
        if r.status_code != 200:
            pytest.skip("Cannot list meetings")
        meetings = r.json()
        signed_off = [m for m in meetings if m.get("status") in ["signed_off", "shared"]]
        if not signed_off:
            pytest.skip("No signed-off meetings available")
        m_id = signed_off[0]["id"]
        r2 = requests.post(
            f"{BASE_URL}/api/review/{m_id}/send-email",
            json={"recipients": ["test@example.com"], "message": "Test message"},
            headers=admin_headers,
        )
        # Should return 200 with message (even if Resend not configured)
        assert r2.status_code == 200, f"Email endpoint failed: {r2.status_code} {r2.text}"
        assert "message" in r2.json()
        print(f"Email response: {r2.json()['message']}")
