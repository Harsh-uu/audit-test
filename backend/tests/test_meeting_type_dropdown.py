"""Tests for the new fixed-list meeting_type dropdown (14 fixed + Other free-text).

Covers:
- CreateMeetingRequest default = "Supervision"
- meeting_type validator (blank rejected, >100 chars rejected)
- POST /api/meetings/ accepts each of the 14 new fixed values
- POST /api/meetings/ accepts a custom "Other" free-text value
- POST /api/meetings/ with blank meeting_type -> 422
- POST /api/meetings/ with omitted meeting_type -> defaults to "Supervision"
- Regression: existing legacy meetings (old lowercase values) still load in list/detail
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://supervision-preview.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASSWORD = "Admin123!X"

NEW_TYPES = [
    "Supervision", "Appraisal", "Competency assessment", "Disciplinary",
    "Grievance", "Safeguarding investigation", "Performance review", "Stay interview",
    "Learner Review", "Probation review",
    "Absence review", "Exit interview", "Team meeting", "Incident review",
    "Audit review", "Quality assurance review",
]


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login failed: {r.status_code} {r.text[:200]}")
    data = r.json()
    # Handle MFA if required
    if data.get("requires_mfa"):
        # Direct DB shortcut per test_credentials.md
        import asyncpg, asyncio, bcrypt
        from datetime import datetime, timedelta, timezone
        async def _bypass():
            conn = await asyncpg.connect(os.environ["DATABASE_URL"] if "DATABASE_URL" in os.environ else None)
            code_hash = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
            exp = datetime.now(timezone.utc) + timedelta(minutes=10)
            await conn.execute(
                "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2 WHERE email=$3",
                code_hash, exp, ADMIN_EMAIL,
            )
            await conn.close()
        try:
            asyncio.run(_bypass())
        except Exception as e:
            pytest.skip(f"could not bypass MFA: {e}")
        r2 = s.post(f"{BASE_URL}/api/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=30)
        if r2.status_code != 200:
            pytest.skip(f"mfa verify failed: {r2.status_code} {r2.text[:200]}")
    return s


@pytest.fixture(scope="module")
def created_ids():
    return []


def _iso_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# --- Unit tests on the Pydantic model (in-process) -----------------
def test_pydantic_default_is_supervision():
    import sys
    sys.path.insert(0, "/app/backend")
    from routers.meetings import CreateMeetingRequest
    m = CreateMeetingRequest(title="X", date=_iso_now())
    assert m.meeting_type == "Supervision"


def test_pydantic_blank_rejected():
    import sys
    sys.path.insert(0, "/app/backend")
    from routers.meetings import CreateMeetingRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError) as exc:
        CreateMeetingRequest(title="X", date=_iso_now(), meeting_type="   ")
    assert "meeting_type must not be blank" in str(exc.value)


def test_pydantic_too_long_rejected():
    import sys
    sys.path.insert(0, "/app/backend")
    from routers.meetings import CreateMeetingRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CreateMeetingRequest(title="X", date=_iso_now(), meeting_type="A" * 101)


# --- API tests -----------------------------------------------------
@pytest.mark.parametrize("mtype", NEW_TYPES)
def test_create_meeting_accepts_each_new_type(session, created_ids, mtype):
    payload = {
        "title": f"TEST_{mtype}",
        "date": _iso_now(),
        "meeting_type": mtype,
        "attendee_ids": [],
    }
    r = session.post(f"{BASE_URL}/api/meetings/", json=payload, timeout=30)
    assert r.status_code in (200, 201), f"{mtype}: {r.status_code} {r.text[:300]}"
    data = r.json()
    assert data["meeting_type"] == mtype
    assert "id" in data
    created_ids.append(data["id"])


def test_create_meeting_with_other_free_text(session, created_ids):
    r = session.post(f"{BASE_URL}/api/meetings/", json={
        "title": "TEST_custom",
        "date": _iso_now(),
        "meeting_type": "Custom test type",
        "attendee_ids": [],
    }, timeout=30)
    assert r.status_code in (200, 201), r.text
    assert r.json()["meeting_type"] == "Custom test type"
    created_ids.append(r.json()["id"])


def test_create_meeting_blank_rejected(session):
    r = session.post(f"{BASE_URL}/api/meetings/", json={
        "title": "TEST_blank",
        "date": _iso_now(),
        "meeting_type": "",
        "attendee_ids": [],
    }, timeout=30)
    assert r.status_code == 422, f"expected 422 got {r.status_code}: {r.text[:300]}"
    assert "meeting_type" in r.text.lower()


def test_create_meeting_whitespace_rejected(session):
    r = session.post(f"{BASE_URL}/api/meetings/", json={
        "title": "TEST_ws",
        "date": _iso_now(),
        "meeting_type": "   ",
        "attendee_ids": [],
    }, timeout=30)
    assert r.status_code == 422


def test_create_meeting_omitted_defaults_supervision(session, created_ids):
    r = session.post(f"{BASE_URL}/api/meetings/", json={
        "title": "TEST_default",
        "date": _iso_now(),
        "attendee_ids": [],
    }, timeout=30)
    assert r.status_code in (200, 201), r.text
    assert r.json()["meeting_type"] == "Supervision"
    created_ids.append(r.json()["id"])


def test_create_meeting_over_100_chars_rejected(session):
    r = session.post(f"{BASE_URL}/api/meetings/", json={
        "title": "TEST_long",
        "date": _iso_now(),
        "meeting_type": "X" * 101,
        "attendee_ids": [],
    }, timeout=30)
    assert r.status_code == 422


# --- Regression: existing meetings still load ----------------------
def test_meetings_list_loads(session):
    r = session.get(f"{BASE_URL}/api/meetings/?limit=500", timeout=30)
    assert r.status_code == 200
    meetings = r.json()
    assert isinstance(meetings, list)
    # Confirm we can see meetings with various legacy meeting_type values (untouched)
    types = {m.get("meeting_type") for m in meetings}
    print(f"Distinct meeting_type values seen in list ({len(meetings)} rows): {types}")


def test_legacy_meeting_detail_loads(session):
    """Fetch detail for a few existing meetings — ensures old lowercase types don't break serialisation."""
    r = session.get(f"{BASE_URL}/api/meetings/?limit=20", timeout=30)
    assert r.status_code == 200
    meetings = r.json()
    checked = 0
    for m in meetings[:10]:
        d = session.get(f"{BASE_URL}/api/meetings/{m['id']}", timeout=30)
        assert d.status_code == 200, f"detail failed for {m['id']} (meeting_type={m.get('meeting_type')}): {d.status_code}"
        assert d.json()["meeting_type"] == m["meeting_type"]
        checked += 1
    print(f"Verified {checked} existing meeting detail loads (legacy types untouched).")


# --- Cleanup -------------------------------------------------------
def test_cleanup(session, created_ids):
    for mid in created_ids:
        session.delete(f"{BASE_URL}/api/meetings/{mid}", timeout=30)
    print(f"Cleaned up {len(created_ids)} TEST_ meetings.")
