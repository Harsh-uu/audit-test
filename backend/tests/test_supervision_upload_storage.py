"""
Tests for supervision doc-uploads storage_path feature (iteration 123).

Covers:
- New POST /api/doc-uploads/ persists file to storage (DOCX + PDF)
- GET /api/doc-uploads/{id}/download returns byte-identical file
- 403 for attendee role, 404 for nonexistent id
- DELETE removes DB row and best-effort cleans storage; 404 for missing id
- Full lifecycle: upload -> status transitions -> AI mapping -> evidence update
"""
import io
import os
import time
import uuid
import zipfile

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
def manager_sess():
    return _login_session(*MANAGER)


@pytest.fixture(scope="module")
def admin_sess():
    return _login_session(*ADMIN)


@pytest.fixture(scope="module")
def attendee_sess():
    return _login_session(*ATTENDEE)


# --- Minimal valid PDF ---
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


def _make_docx(text="Supervision meeting notes: staff completed safeguarding training and demonstrated understanding of duty of care. Care Certificate Standard 10 was discussed. Manager confirmed CQC Safe key line compliance."):
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
            f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>'
            '</w:document>')
    return buf.getvalue()


def _get_staff_id(sess):
    r = sess.get(f"{API}/admin/users", timeout=15)
    assert r.status_code == 200, r.text
    users = r.json()
    staff = [u for u in users if u.get("role") == "attendee"]
    assert staff, "No attendee users found in org"
    return staff[0]["id"]


def _upload_doc(sess, filename, data, content_type, staff_id, label="TEST_supervision"):
    files = {"file": (filename, data, content_type)}
    form = {
        "staff_id": staff_id,
        "label": label,
        "meeting_date": "2025-01-15",
        "doc_type": "supervision",
    }
    return sess.post(f"{API}/doc-uploads/", files=files, data=form, timeout=30)


class TestDocxUploadDownload:
    def test_docx_upload_and_download(self, manager_sess):
        staff_id = _get_staff_id(manager_sess)
        docx = _make_docx()

        r = _upload_doc(manager_sess, "test_supervision.docx", docx,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        staff_id, label="TEST_docx_lifecycle")
        assert r.status_code == 200, r.text
        upload = r.json()
        upload_id = upload["id"]
        assert upload["status"] == "processing"
        assert upload["file_ext"] == "docx"

        try:
            # Immediately try download (storage persisted BEFORE background AI task starts)
            d = manager_sess.get(f"{API}/doc-uploads/{upload_id}/download", timeout=20)
            assert d.status_code == 200, f"Download failed: {d.status_code} {d.text[:200]}"
            assert d.content == docx, "DOCX byte mismatch"
            cd = d.headers.get("content-disposition", "")
            assert "test_supervision.docx" in cd
            print(f"DOCX download OK: {len(d.content)} bytes")
        finally:
            manager_sess.delete(f"{API}/doc-uploads/{upload_id}", timeout=15)

    def test_pdf_upload_and_download(self, manager_sess):
        staff_id = _get_staff_id(manager_sess)
        r = _upload_doc(manager_sess, "test_supervision.pdf", MINIMAL_PDF,
                        "application/pdf", staff_id, label="TEST_pdf")
        assert r.status_code == 200, r.text
        upload_id = r.json()["id"]
        try:
            d = manager_sess.get(f"{API}/doc-uploads/{upload_id}/download", timeout=20)
            assert d.status_code == 200
            assert d.content == MINIMAL_PDF, "PDF byte mismatch"
            assert "pdf" in (d.headers.get("content-type") or "").lower()
        finally:
            manager_sess.delete(f"{API}/doc-uploads/{upload_id}", timeout=15)


class TestPermissions:
    def test_attendee_forbidden_download(self, manager_sess, attendee_sess):
        staff_id = _get_staff_id(manager_sess)
        r = _upload_doc(manager_sess, "test_403.docx", _make_docx(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        staff_id, label="TEST_403")
        assert r.status_code == 200
        upload_id = r.json()["id"]
        try:
            d = attendee_sess.get(f"{API}/doc-uploads/{upload_id}/download", timeout=15)
            assert d.status_code == 403
        finally:
            manager_sess.delete(f"{API}/doc-uploads/{upload_id}", timeout=15)

    def test_attendee_forbidden_upload(self, attendee_sess):
        r = _upload_doc(attendee_sess, "x.docx", _make_docx(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "some-id", label="TEST_403_up")
        assert r.status_code == 403

    def test_download_404_nonexistent(self, manager_sess):
        fake = str(uuid.uuid4())
        d = manager_sess.get(f"{API}/doc-uploads/{fake}/download", timeout=15)
        assert d.status_code == 404


class TestDeleteBehavior:
    def test_delete_removes_row_and_404_after(self, manager_sess):
        staff_id = _get_staff_id(manager_sess)
        r = _upload_doc(manager_sess, "test_del.docx", _make_docx(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        staff_id, label="TEST_del")
        assert r.status_code == 200
        upload_id = r.json()["id"]

        d = manager_sess.delete(f"{API}/doc-uploads/{upload_id}", timeout=15)
        assert d.status_code == 200

        # Subsequent GET should 404
        g = manager_sess.get(f"{API}/doc-uploads/{upload_id}", timeout=10)
        assert g.status_code == 404

        # Delete again should 404
        d2 = manager_sess.delete(f"{API}/doc-uploads/{upload_id}", timeout=10)
        assert d2.status_code == 404

        # Download after delete should 404
        d3 = manager_sess.get(f"{API}/doc-uploads/{upload_id}/download", timeout=10)
        assert d3.status_code == 404

    def test_delete_nonexistent_404(self, manager_sess):
        fake = str(uuid.uuid4())
        d = manager_sess.delete(f"{API}/doc-uploads/{fake}", timeout=10)
        assert d.status_code == 404


class TestLifecycleRegression:
    def test_full_lifecycle_status_and_evidence(self, manager_sess):
        staff_id = _get_staff_id(manager_sess)
        docx = _make_docx()
        r = _upload_doc(manager_sess, "test_lifecycle.docx", docx,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        staff_id, label="TEST_lifecycle_full")
        assert r.status_code == 200
        upload_id = r.json()["id"]
        assert r.json()["status"] == "processing"

        try:
            # Wait for background processing (text_ready -> done or failed)
            final_status = None
            for _ in range(30):
                time.sleep(3)
                g = manager_sess.get(f"{API}/doc-uploads/{upload_id}", timeout=10)
                assert g.status_code == 200
                status = g.json()["status"]
                if status in ("done", "failed"):
                    final_status = status
                    break
            assert final_status in ("done", "failed"), f"Stuck in status={final_status}"
            print(f"Final AI status: {final_status}")

            # If done, ensure mappings arrays exist (may be empty depending on AI)
            data = manager_sess.get(f"{API}/doc-uploads/{upload_id}", timeout=10).json()
            for f in ("cqc_mappings", "care_cert_mappings", "custom_mappings"):
                assert isinstance(data.get(f), list)

            # If mappings present, exercise evidence update endpoint (regression)
            for f in ("cqc_mappings", "care_cert_mappings", "custom_mappings"):
                items = data.get(f) or []
                if items and items[0].get("id"):
                    ev_id = items[0]["id"]
                    upd = manager_sess.put(
                        f"{API}/doc-uploads/{upload_id}/evidence/{ev_id}",
                        json={"status": "accepted", "notes": "TEST_note"},
                        timeout=15)
                    assert upd.status_code == 200, upd.text
                    print(f"Evidence update on {f}[0] OK")
                    break
        finally:
            manager_sess.delete(f"{API}/doc-uploads/{upload_id}", timeout=15)
