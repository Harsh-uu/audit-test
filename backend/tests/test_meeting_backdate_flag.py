"""Regression test for: "Meeting date is not validated against live recording
timestamp."

Fix policy (confirmed with the user): never block meeting creation or
recording on a backdated/postdated `date` — just detect a large mismatch
between the declared meeting date and the real recording-start time, and
surface it transparently as a 'meeting_backdated' Audit Trail entry plus a
`date_flagged`/`date_flag_detail` pair on GET /meetings/{id}.

Covers:
  - a meeting dated well in the past, recorded "now", gets flagged
  - a meeting dated ~now, recorded "now", is NOT flagged (no false positives)
  - starting recording twice doesn't create duplicate flag entries
"""
import asyncio
from datetime import datetime, timezone

import pytest
import requests
from dotenv import dotenv_values

fe = dotenv_values("/app/frontend/.env")
BASE = fe["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=90)
    if r.status_code != 200:
        pytest.fail(f"Login failed for {email}: {r.status_code} {r.text[:300]}")
    return s


@pytest.fixture(scope="module")
def manager():
    return _login("manager@supervision.com", "Manager123!")


def _create_meeting(s, date_str, title):
    r = s.post(f"{BASE}/meetings/", json={
        "title": title, "date": date_str, "location": "Room 1", "attendees": []
    })
    assert r.status_code in (200, 201), f"Create meeting failed: {r.text}"
    return r.json()["id"]


def _start_recording(s, meeting_id):
    ts = datetime.now(timezone.utc).isoformat()
    r = s.post(f"{BASE}/recording/{meeting_id}/start", json={"timestamp": ts})
    assert r.status_code == 200, f"start_recording failed: {r.text}"
    return ts


def _audit_events(s, meeting_id):
    r = s.get(f"{BASE}/review/{meeting_id}/audit-trail")
    assert r.status_code == 200, f"audit-trail failed: {r.text}"
    return r.json()["events"]


def _get_meeting(s, meeting_id):
    r = s.get(f"{BASE}/meetings/{meeting_id}")
    assert r.status_code == 200, f"get_meeting failed: {r.text}"
    return r.json()


def _cleanup(s, meeting_id):
    s.delete(f"{BASE}/meetings/{meeting_id}")


def test_backdated_meeting_is_flagged_not_blocked(manager):
    """A meeting dated well in the past must still create/record successfully
    (no blocking), but the mismatch must surface in the Audit Trail and on
    the meeting object."""
    meeting_id = _create_meeting(manager, "2025-02-07T09:00:00", "TEST_Backdated Meeting")
    try:
        # Creation and recording start must both succeed — the fix never blocks.
        _start_recording(manager, meeting_id)

        events = _audit_events(manager, meeting_id)
        backdated = [e for e in events if e["type"] == "meeting_backdated"]
        assert len(backdated) == 1, f"Expected exactly one meeting_backdated event, got: {events}"
        assert backdated[0].get("flagged") is True, f"meeting_backdated event should be flagged: {backdated[0]}"
        assert backdated[0].get("detail"), "meeting_backdated event should carry an explanatory detail"

        meeting = _get_meeting(manager, meeting_id)
        assert meeting["date_flagged"] is True
        assert meeting.get("date_flag_detail")
    finally:
        _cleanup(manager, meeting_id)


def test_recent_meeting_is_not_flagged(manager):
    """A meeting dated ~now, recorded now, must NOT be flagged — no false positives."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    meeting_id = _create_meeting(manager, now_str, "TEST_On-time Meeting")
    try:
        _start_recording(manager, meeting_id)

        events = _audit_events(manager, meeting_id)
        backdated = [e for e in events if e["type"] == "meeting_backdated"]
        assert backdated == [], f"Unexpected meeting_backdated event for an on-time meeting: {backdated}"

        meeting = _get_meeting(manager, meeting_id)
        assert meeting["date_flagged"] is False
        assert meeting.get("date_flag_detail") is None
    finally:
        _cleanup(manager, meeting_id)


def test_flag_is_not_duplicated_on_repeated_start(manager):
    """Starting recording more than once on the same backdated meeting must
    only ever produce one meeting_backdated audit entry."""
    meeting_id = _create_meeting(manager, "2024-06-01T10:00:00", "TEST_Backdated Repeat Start")
    try:
        _start_recording(manager, meeting_id)
        _start_recording(manager, meeting_id)

        events = _audit_events(manager, meeting_id)
        backdated = [e for e in events if e["type"] == "meeting_backdated"]
        assert len(backdated) == 1, f"meeting_backdated should be idempotent, got: {backdated}"
    finally:
        _cleanup(manager, meeting_id)
