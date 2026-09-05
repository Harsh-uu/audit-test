"""
Test the P1 fix: PII redactions must also apply to attendee/manager names
in PDF metadata / CSV staff columns for all export endpoints — not just
the transcript/analysis body.

Seed strategy: create 2 signed-off meetings with an analysis each:
  * meeting_R  — pii_redactions redact "Demo Manager" and "Demo User" -> [Redacted]
  * meeting_NR — pii_redactions = [] (regression: names must appear unchanged)

Then hit each export endpoint (as manager or admin), extract PDF text via
pypdf, and assert:
  * meeting_R:  raw names ABSENT and "[Redacted]" PRESENT in metadata
  * meeting_NR: raw names PRESENT (regression / no behaviour change)
"""
import asyncio
import io
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values
from pypdf import PdfReader

BE = dotenv_values("/app/backend/.env")
FE = dotenv_values("/app/frontend/.env")
BASE = FE["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]

MGR_EMAIL = "manager@supervision.com"
MGR_PW = "Manager123!"
ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PW = "Admin123!"

TRANSCRIPT_TEMPLATE = (
    "Manager: Hello Demo User, how are you.\n"
    "Staff: Hi Demo Manager, I am well thank you.\n"
    "Manager: We discussed medication management with Demo User today.\n"
)

RAW_MANAGER_NAME = "Demo Manager"
RAW_STAFF_NAME = "Demo User"
REDACTED = "[Redacted]"


# ---------- login helper (uses same pattern as get_tokens.py) ----------
async def _override_mfa(email):
    conn = await asyncpg.connect(DSN, ssl="require")
    from datetime import timedelta
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email,
    )
    await conn.close()


def _login(email, pw):
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=60)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_override_mfa(email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"},
                    timeout=60)
        assert r2.status_code == 200, f"mfa failed: {r2.text[:200]}"
    return s


# ---------- seed helper ----------
async def _seed_meetings():
    """Create two signed-off meetings + analyses. Returns (meeting_with_redactions_id, meeting_without_id)."""
    conn = await asyncpg.connect(DSN, ssl="require")
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    now_naive = now.replace(tzinfo=None)
    try:
        mgr = await conn.fetchrow("SELECT id, name, org_id FROM users WHERE email=$1", MGR_EMAIL)
        staff = await conn.fetchrow("SELECT id, name, email FROM users WHERE email=$1", "user@supervision.com")
        assert mgr and staff

        results = {}
        for key, redactions in [
            ("with", [
                {"original": RAW_MANAGER_NAME, "replacement": REDACTED},
                {"original": RAW_STAFF_NAME, "replacement": REDACTED},
            ]),
            ("without", []),
        ]:
            mid = str(uuid.uuid4())
            tid = str(uuid.uuid4())
            aid = str(uuid.uuid4())
            attendees = [
                {"user_id": str(staff["id"]), "name": staff["name"], "email": staff["email"],
                 "role": "supervisee", "reviewed": True},
                {"user_id": str(mgr["id"]), "name": mgr["name"], "email": MGR_EMAIL,
                 "role": "manager", "reviewed": True},
            ]
            sign_off_record = {
                "signed_by_id": str(mgr["id"]),
                "signed_by_name": mgr["name"],
                "signed_at": now_iso,
            }
            # Insert meeting first (FK constraints require meetings.id to exist)
            await conn.execute(
                """INSERT INTO meetings (id, org_id, title, date, location, meeting_type, created_by,
                   created_by_name, sign_off_manager_id, sign_off_manager_name, attendees, status,
                   pii_redactions, sign_off_record, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,'supervision',$6,$7,$6,$7,$8::jsonb,'signed_off',
                   $9::jsonb,$10::jsonb,$11,$11)""",
                mid, mgr["org_id"], f"TEST_PII_EXPORT_{key}", now_naive, "Test Room",
                mgr["id"], mgr["name"], json.dumps(attendees),
                json.dumps(redactions), json.dumps(sign_off_record), now,
            )
            await conn.execute(
                "INSERT INTO transcripts (id, meeting_id, org_id, text, speaker_text, created_at) "
                "VALUES ($1,$2,$3,$4,$5,$6)",
                tid, mid, mgr["org_id"], TRANSCRIPT_TEMPLATE, TRANSCRIPT_TEMPLATE, now,
            )
            await conn.execute(
                """INSERT INTO analyses (id, meeting_id, org_id, summary, achievements, actions,
                   learning_needs, risks, cqc_mappings, care_cert_mappings, custom_mappings, created_at)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8::jsonb,$9::jsonb,$10::jsonb,$11::jsonb,$12)""",
                aid, mid, mgr["org_id"],
                f"Summary mentions {RAW_MANAGER_NAME} and {RAW_STAFF_NAME}.",
                json.dumps([{"description": "Ach 1"}]),
                json.dumps([{"text": "Do X", "owner": "Manager", "due_date": "2026-06-01", "status": "open"}]),
                json.dumps([{"text": "L1"}]),
                json.dumps([]),
                json.dumps([{
                    "regulation_ref": "R9", "regulation_name": "Person-centred care",
                    "confidence": "high", "status": "accepted",
                    "evidence_summary": f"{RAW_STAFF_NAME} demonstrated person-centred care.",
                    "excerpt": "excerpt text",
                }]),
                json.dumps([{
                    "standard_ref": "1", "standard_name": "Understand your role",
                    "confidence": "high", "status": "accepted",
                    "evidence_summary": f"{RAW_STAFF_NAME} discussed role clarity.",
                    "excerpt": "excerpt",
                }]),
                json.dumps([]),
                now,
            )
            await conn.execute(
                "UPDATE meetings SET transcript_id=$1, analysis_id=$2 WHERE id=$3",
                tid, aid, mid,
            )
            results[key] = mid
        return results["with"], results["without"], str(mgr["id"]), str(staff["id"])
    finally:
        await conn.close()


async def _cleanup():
    conn = await asyncpg.connect(DSN, ssl="require")
    try:
        ids = await conn.fetch("SELECT id FROM meetings WHERE title LIKE 'TEST_PII_EXPORT_%'")
        mids = [r["id"] for r in ids]
        if mids:
            await conn.execute("DELETE FROM analyses WHERE meeting_id = ANY($1::uuid[])", mids)
            await conn.execute("DELETE FROM transcripts WHERE meeting_id = ANY($1::uuid[])", mids)
            await conn.execute("DELETE FROM meetings WHERE id = ANY($1::uuid[])", mids)
    finally:
        await conn.close()


# ---------- pytest fixtures ----------
@pytest.fixture(scope="module")
def seeded():
    asyncio.run(_cleanup())
    with_id, without_id, mgr_id, staff_id = asyncio.run(_seed_meetings())
    yield {"with": with_id, "without": without_id, "mgr_id": mgr_id, "staff_id": staff_id}
    asyncio.run(_cleanup())


@pytest.fixture(scope="module")
def mgr_session():
    return _login(MGR_EMAIL, MGR_PW)


@pytest.fixture(scope="module")
def admin_session():
    return _login(ADMIN_EMAIL, ADMIN_PW)


# ---------- utility: extract PDF text ----------
def _pdf_text(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


# ==================== review.py export-pdf ====================
def test_review_export_pdf_with_redactions_hides_names(seeded, mgr_session):
    r = mgr_session.get(f"{BASE}/review/{seeded['with']}/export-pdf", timeout=60)
    assert r.status_code == 200, r.text[:300]
    assert r.headers.get("content-type", "").startswith("application/pdf")
    txt = _pdf_text(r.content)
    assert REDACTED in txt, f"[Redacted] must appear in metadata; got: {txt[:1000]}"
    assert RAW_MANAGER_NAME not in txt, "Raw manager name leaked in PDF"
    assert RAW_STAFF_NAME not in txt, "Raw staff/attendee name leaked in PDF"


def test_review_export_pdf_without_redactions_shows_full_names(seeded, mgr_session):
    r = mgr_session.get(f"{BASE}/review/{seeded['without']}/export-pdf", timeout=60)
    assert r.status_code == 200, r.text[:300]
    txt = _pdf_text(r.content)
    assert RAW_MANAGER_NAME in txt, "Manager name missing in no-redaction PDF (regression)"
    assert RAW_STAFF_NAME in txt, "Staff name missing in no-redaction PDF (regression)"


# ==================== review.py export-transcript ====================
def test_review_export_transcript_with_redactions(seeded, mgr_session):
    r = mgr_session.get(f"{BASE}/review/{seeded['with']}/export-transcript", timeout=60)
    assert r.status_code == 200, r.text[:300]
    assert r.headers.get("content-type", "").startswith("application/pdf")
    txt = _pdf_text(r.content)
    assert RAW_MANAGER_NAME not in txt, "Raw manager name leaked in transcript PDF"
    assert RAW_STAFF_NAME not in txt, "Raw staff name leaked in transcript PDF"
    assert REDACTED in txt


def test_review_export_transcript_without_redactions(seeded, mgr_session):
    r = mgr_session.get(f"{BASE}/review/{seeded['without']}/export-transcript", timeout=60)
    assert r.status_code == 200
    txt = _pdf_text(r.content)
    assert RAW_MANAGER_NAME in txt
    assert RAW_STAFF_NAME in txt


# ==================== admin.py export-evidence PDF ====================
def test_admin_export_evidence_pdf_with_redactions(seeded, admin_session):
    r = admin_session.post(f"{BASE}/admin/export-evidence",
                           json={"format": "pdf", "meeting_ids": [seeded["with"]]},
                           timeout=60)
    assert r.status_code == 200, r.text[:300]
    assert r.headers.get("content-type", "").startswith("application/pdf")
    txt = _pdf_text(r.content)
    assert RAW_MANAGER_NAME not in txt, "Raw manager name leaked in evidence PDF"
    assert RAW_STAFF_NAME not in txt, "Raw staff name leaked in evidence PDF"
    assert REDACTED in txt


def test_admin_export_evidence_pdf_without_redactions(seeded, admin_session):
    r = admin_session.post(f"{BASE}/admin/export-evidence",
                           json={"format": "pdf", "meeting_ids": [seeded["without"]]},
                           timeout=60)
    assert r.status_code == 200
    txt = _pdf_text(r.content)
    assert RAW_MANAGER_NAME in txt
    assert RAW_STAFF_NAME in txt


# ==================== admin.py export-evidence CSV ====================
def test_admin_export_evidence_csv_with_redactions(seeded, admin_session):
    r = admin_session.post(f"{BASE}/admin/export-evidence",
                           json={"format": "csv", "meeting_ids": [seeded["with"]]},
                           timeout=60)
    assert r.status_code == 200, r.text[:300]
    assert r.headers.get("content-type", "").startswith("text/csv")
    body = r.content.decode("utf-8-sig")
    # Staff Member column is the first column of each data row
    assert RAW_STAFF_NAME not in body, f"Raw staff name leaked in CSV: {body[:500]}"
    # Manager isn't listed as a row (excluded because sign_off_mgr_id) but the CSV
    # should still be redacted for the supervisee row
    assert REDACTED in body


def test_admin_export_evidence_csv_without_redactions(seeded, admin_session):
    r = admin_session.post(f"{BASE}/admin/export-evidence",
                           json={"format": "csv", "meeting_ids": [seeded["without"]]},
                           timeout=60)
    assert r.status_code == 200
    body = r.content.decode("utf-8-sig")
    assert RAW_STAFF_NAME in body, "Regression: staff name missing in no-redaction CSV"


# ==================== admin.py export-cqc-excerpts ====================
def test_admin_export_cqc_excerpts_reflects_redactions(seeded, admin_session):
    """Excerpts endpoint returns ALL org meetings — both meetings should appear.
    The redacted meeting's metadata line must be redacted, the other must show real names."""
    r = admin_session.get(f"{BASE}/admin/export-cqc-excerpts", timeout=60)
    assert r.status_code == 200, r.text[:300]
    txt = _pdf_text(r.content)
    # The 'with' meeting was seeded with a CQC mapping. Redacted line should contain [Redacted]
    assert REDACTED in txt, "Redacted metadata expected somewhere in CQC excerpts"
    # The 'without' meeting was also seeded with a CQC mapping and has RAW names
    assert RAW_MANAGER_NAME in txt or RAW_STAFF_NAME in txt, \
        "No-redaction meeting must still show real names (regression)"


# ==================== admin.py export-cc-excerpts ====================
def test_admin_export_cc_excerpts_reflects_redactions(seeded, admin_session):
    r = admin_session.get(f"{BASE}/admin/export-cc-excerpts", timeout=60)
    assert r.status_code == 200, r.text[:300]
    txt = _pdf_text(r.content)
    assert REDACTED in txt
    assert RAW_MANAGER_NAME in txt or RAW_STAFF_NAME in txt, \
        "No-redaction meeting must still show real names (regression)"


# ==================== admin.py export-transcripts (bulk) ====================
def test_admin_export_transcripts_with_redactions(seeded, admin_session):
    r = admin_session.post(f"{BASE}/admin/export-transcripts",
                           json={"meeting_ids": [seeded["with"]]},
                           timeout=60)
    assert r.status_code == 200, r.text[:300]
    assert r.headers.get("content-type", "").startswith("application/pdf")
    txt = _pdf_text(r.content)
    assert RAW_MANAGER_NAME not in txt, "Raw manager name leaked in bulk transcripts PDF"
    assert RAW_STAFF_NAME not in txt, "Raw staff name leaked in bulk transcripts PDF"
    assert REDACTED in txt


def test_admin_export_transcripts_without_redactions(seeded, admin_session):
    r = admin_session.post(f"{BASE}/admin/export-transcripts",
                           json={"meeting_ids": [seeded["without"]]},
                           timeout=60)
    assert r.status_code == 200
    txt = _pdf_text(r.content)
    assert RAW_MANAGER_NAME in txt
    assert RAW_STAFF_NAME in txt
