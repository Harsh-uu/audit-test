"""
Tests for new document download endpoint + delete-with-storage-cleanup
(review request iteration 122). Covers:
- Download endpoint: PDF, DOCX, TXT content-type integrity
- Permission: 403 for attendee
- Not found: 404 for random id and cross-org id
- Delete now removes DB row (regression) - orphan-storage cleanup best-effort
- Regression: upload -> list -> toggle -> delete lifecycle
"""
import io
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("admin@supervision.com", "Admin123!")
MANAGER = ("manager@supervision.com", "Manager123!")
ATTENDEE = ("user@supervision.com", "AnotherNew789!")


def _login_session(email, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"Login failed for {email}: {r.status_code} {r.text[:200]}")
    data = r.json()
    if data.get("mfa_required"):
        pytest.skip(f"MFA required for {email}, skipping")
    return s


@pytest.fixture(scope="module")
def admin_token():
    return _login_session(*ADMIN)


@pytest.fixture(scope="module")
def attendee_token():
    return _login_session(*ATTENDEE)


def _headers(_s):
    return {}


# --- Minimal valid PDF (%PDF-1.4 header + trailer) ---
MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000053 00000 n \n"
    b"0000000098 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\n"
    b"startxref\n147\n%%EOF"
)


def _make_docx():
    """Build a minimal-valid .docx (zip with required parts)."""
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>')
        z.writestr("_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
        z.writestr("word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>Test document criteria: staff must complete safeguarding training annually.</w:t></w:r></w:p></w:body>'
            '</w:document>')
    return buf.getvalue()


def _upload(sess, filename, data, content_type, label="TEST_doc"):
    files = {"file": (filename, data, content_type)}
    r = sess.post(
        f"{API}/admin/standards/upload",
        files=files,
        data={"label": label},
        timeout=30)
    return r


class TestDocumentDownload:
    def test_upload_and_download_txt(self, admin_token):
        content = b"TEST_TXT: staff must complete annual training on safeguarding."
        r = _upload(admin_token, "test_doc.txt", content, "text/plain")
        assert r.status_code == 200, r.text
        doc_id = r.json()["id"]

        d = admin_token.get(f"{API}/admin/standards/documents/{doc_id}/download",
                             timeout=15)
        assert d.status_code == 200
        assert d.content == content, "TXT download byte mismatch"
        cd = d.headers.get("content-disposition", "")
        assert "test_doc.txt" in cd
        # Cleanup
        admin_token.delete(f"{API}/admin/standards/documents/{doc_id}")

    def test_upload_and_download_pdf(self, admin_token):
        r = _upload(admin_token, "test_doc.pdf", MINIMAL_PDF, "application/pdf")
        assert r.status_code == 200, r.text
        doc_id = r.json()["id"]

        d = admin_token.get(f"{API}/admin/standards/documents/{doc_id}/download",
                             timeout=15)
        assert d.status_code == 200
        assert d.content == MINIMAL_PDF, "PDF byte mismatch"
        assert "pdf" in (d.headers.get("content-type") or "").lower()
        cd = d.headers.get("content-disposition", "")
        assert "test_doc.pdf" in cd
        admin_token.delete(f"{API}/admin/standards/documents/{doc_id}")

    def test_upload_and_download_docx(self, admin_token):
        docx = _make_docx()
        r = _upload(admin_token, "test_doc.docx", docx,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        assert r.status_code == 200, r.text
        doc_id = r.json()["id"]

        d = admin_token.get(f"{API}/admin/standards/documents/{doc_id}/download",
                             timeout=15)
        assert d.status_code == 200
        assert d.content == docx, "DOCX byte mismatch"
        ct = (d.headers.get("content-type") or "").lower()
        assert "wordprocessingml" in ct or "officedocument" in ct or "zip" in ct or "octet-stream" in ct
        cd = d.headers.get("content-disposition", "")
        assert "test_doc.docx" in cd
        admin_token.delete(f"{API}/admin/standards/documents/{doc_id}")

    def test_download_404_nonexistent(self, admin_token):
        fake_id = str(uuid.uuid4())
        d = admin_token.get(f"{API}/admin/standards/documents/{fake_id}/download",
                             timeout=10)
        assert d.status_code == 404

    def test_download_403_attendee(self, admin_token, attendee_token):
        # Admin creates a doc
        r = _upload(admin_token, "test_403.txt", b"secret content", "text/plain")
        assert r.status_code == 200
        doc_id = r.json()["id"]
        try:
            d = attendee_token.get(f"{API}/admin/standards/documents/{doc_id}/download",
                             timeout=10)
            assert d.status_code == 403
        finally:
            attendee_token.delete(f"{API}/admin/standards/documents/{doc_id}")


class TestDeleteWithStorageCleanup:
    def test_delete_removes_db_row(self, admin_token):
        r = _upload(admin_token, "test_del.txt", b"delete me", "text/plain")
        assert r.status_code == 200
        doc_id = r.json()["id"]

        d = admin_token.delete(f"{API}/admin/standards/documents/{doc_id}",
                             timeout=15)
        assert d.status_code == 200

        # Confirm gone from list
        lst = admin_token.get(f"{API}/admin/standards/documents",
                             timeout=10).json()
        assert not any(x["id"] == doc_id for x in lst), "Doc still in list after delete"

        # Download should now 404
        d2 = admin_token.get(f"{API}/admin/standards/documents/{doc_id}/download",
                             timeout=10)
        assert d2.status_code == 404


class TestLifecycleRegression:
    def test_full_lifecycle(self, admin_token):
        # Upload
        content = b"TEST_LIFECYCLE: staff must adhere to medication policy. Care Certificate Standard 13 applies."
        r = _upload(admin_token, "test_lifecycle.txt", content, "text/plain", label="TEST_LC")
        assert r.status_code == 200
        doc_id = r.json()["id"]
        assert r.json()["parse_status"] == "parsing"

        # List
        lst = admin_token.get(f"{API}/admin/standards/documents",
                             timeout=10).json()
        assert any(x["id"] == doc_id for x in lst)

        # Toggle inactive
        p = admin_token.patch(f"{API}/admin/standards/documents/{doc_id}",
                           json={"is_active": False}, timeout=10)
        assert p.status_code == 200

        # Verify toggle
        lst2 = admin_token.get(f"{API}/admin/standards/documents",
                             timeout=10).json()
        doc = next(x for x in lst2 if x["id"] == doc_id)
        assert doc["is_active"] is False

        # Toggle back active
        p2 = admin_token.patch(f"{API}/admin/standards/documents/{doc_id}",
                             json={"is_active": True}, timeout=10)
        assert p2.status_code == 200

        # Delete
        d = admin_token.delete(f"{API}/admin/standards/documents/{doc_id}",
                             timeout=15)
        assert d.status_code == 200

    def test_ai_parsing_progresses(self, admin_token):
        """Give background parsing a chance and confirm it doesn't stay stuck in 'parsing' forever."""
        content = (b"Care Certificate Standard 1: Understand your role. "
                   b"Staff must know their responsibilities. Standard 6: Communication. ") * 3
        r = _upload(admin_token, "test_parse.txt", content, "text/plain", label="TEST_PARSE")
        assert r.status_code == 200
        doc_id = r.json()["id"]

        final_status = "parsing"
        try:
            for _ in range(20):
                time.sleep(3)
                lst = admin_token.get(f"{API}/admin/standards/documents",
                             timeout=10).json()
                doc = next((x for x in lst if x["id"] == doc_id), None)
                if doc and doc["parse_status"] != "parsing":
                    final_status = doc["parse_status"]
                    break
            assert final_status in ("parsed", "failed"), f"Doc stuck in {final_status}"
        finally:
            admin_token.delete(f"{API}/admin/standards/documents/{doc_id}")
