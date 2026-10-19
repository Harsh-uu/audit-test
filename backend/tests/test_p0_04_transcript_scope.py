"""P0-04 regression: GET /{meeting_id}/transcript-text must enforce the same
manager-scope (SEC-002) check as GET /{meeting_id} — a team/setting-scoped
manager must not be able to read the transcript text of a meeting outside
their scope, even though the full meeting-detail endpoint already blocks it.

Uses current, verified test credentials (see /app/memory/test_credentials.md):
  - priyas@1two.one / TestPass123!X — manager scoped to "Team A"
    (team_id=064148ce-efbe-4a59-8fe7-870273580712)
  - jane@supervision.com / JaneNew456! — attendee on team "ONE", outside
    Priya's scope
  - admin@supervision.com / Admin123!X — org-level (unrestricted)
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

import asyncpg
import pytest
import requests
from dotenv import dotenv_values

_be_env = dotenv_values("/app/backend/.env")
_fe_env = dotenv_values("/app/frontend/.env")
_DSN = _be_env.get("DATABASE_URL")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _fe_env.get("REACT_APP_BACKEND_URL", "")).rstrip("/")

ORG_ID = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"  # Test Company
ADMIN_ID = "f72ac550-e6b8-4ffc-b2da-46a54a4c06d5"
JANE_ID = "724367a3-1ca9-498b-890b-0516b2f122f5"  # team "ONE" — outside Priya's "Team A" scope
MARIA_ID = "bf94bf10-b796-476e-a5b5-d598e42d72c4"  # team "Team A" — inside Priya's scope


def _login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    return s


async def _make_meeting(attendee_id, attendee_name, text):
    meeting_id = str(uuid.uuid4())
    transcript_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    conn = await asyncpg.connect(_DSN, ssl="require")
    try:
        attendees = json.dumps([{"user_id": attendee_id, "role": "attendee", "name": attendee_name}])
        await conn.execute(
            "INSERT INTO meetings (id, org_id, title, status, attendees, created_by, transcript_id, created_at) "
            "VALUES ($1::uuid,$2::uuid,'P0-04 regression fixture','draft',$3::jsonb,$4::uuid,$5::uuid,$6)",
            meeting_id, ORG_ID, attendees, ADMIN_ID, transcript_id, now,
        )
        await conn.execute(
            "INSERT INTO transcripts (id, meeting_id, org_id, text, created_at) VALUES ($1::uuid,$2::uuid,$3::uuid,$4,$5)",
            transcript_id, meeting_id, ORG_ID, text, now,
        )
    finally:
        await conn.close()
    return meeting_id


async def _delete_meeting(meeting_id):
    conn = await asyncpg.connect(_DSN, ssl="require")
    try:
        await conn.execute("DELETE FROM meetings WHERE id=$1::uuid", meeting_id)  # transcript cascades via FK
    finally:
        await conn.close()


@pytest.fixture
def out_of_scope_meeting():
    mid = asyncio.run(_make_meeting(JANE_ID, "Jane (out of scope)", "OUT-OF-SCOPE secret transcript text"))
    yield mid
    asyncio.run(_delete_meeting(mid))


@pytest.fixture
def in_scope_meeting():
    mid = asyncio.run(_make_meeting(MARIA_ID, "Maria (in scope)", "IN-SCOPE transcript text"))
    yield mid
    asyncio.run(_delete_meeting(mid))


class TestTranscriptTextManagerScope:
    def test_scoped_manager_blocked_from_out_of_scope_transcript(self, out_of_scope_meeting):
        session = _login("priyas@1two.one", "TestPass123!X")
        r_detail = session.get(f"{BASE_URL}/api/meetings/{out_of_scope_meeting}")
        assert r_detail.status_code == 404, f"Expected meeting-detail 404, got {r_detail.status_code}"
        r_text = session.get(f"{BASE_URL}/api/meetings/{out_of_scope_meeting}/transcript-text")
        assert r_text.status_code == 404, f"P0-04: transcript-text must 404 like meeting-detail, got {r_text.status_code}: {r_text.text}"

    def test_scoped_manager_allowed_in_scope_transcript(self, in_scope_meeting):
        session = _login("priyas@1two.one", "TestPass123!X")
        r_detail = session.get(f"{BASE_URL}/api/meetings/{in_scope_meeting}")
        assert r_detail.status_code == 200
        r_text = session.get(f"{BASE_URL}/api/meetings/{in_scope_meeting}/transcript-text")
        assert r_text.status_code == 200, f"In-scope manager access must still work: {r_text.status_code} {r_text.text}"
        assert r_text.json()["text"] == "IN-SCOPE transcript text"

    def test_admin_unrestricted_by_scope(self, out_of_scope_meeting):
        session = _login("admin@supervision.com", "Admin123!X")
        r_text = session.get(f"{BASE_URL}/api/meetings/{out_of_scope_meeting}/transcript-text")
        assert r_text.status_code == 200, "Admin (org-level scope) must remain unrestricted"

    def test_attendee_can_read_own_meeting_transcript(self, out_of_scope_meeting):
        session = _login("jane@supervision.com", "JaneNew456!")
        r_text = session.get(f"{BASE_URL}/api/meetings/{out_of_scope_meeting}/transcript-text")
        assert r_text.status_code == 200, "Attendee on the meeting must still be able to read their own transcript"
        assert r_text.json()["text"] == "OUT-OF-SCOPE secret transcript text"

    def test_unrelated_attendee_blocked(self, in_scope_meeting):
        """Jane is not a participant of in_scope_meeting (Maria is) — must 404."""
        session = _login("jane@supervision.com", "JaneNew456!")
        r_text = session.get(f"{BASE_URL}/api/meetings/{in_scope_meeting}/transcript-text")
        assert r_text.status_code == 404
