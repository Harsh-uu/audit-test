"""
Regression test for the manager-as-false-shared-supervisee carry-over bug.

Scenario: manager attends BOTH meeting A ("Demo User"'s meeting, with an
incomplete unassigned action) and meeting B ("Jane Smith"'s meeting).
sign_off_manager_id left NULL on both (the exact real-world mistake reported).
Before the fix, the manager's shared presence would incorrectly link the two
meetings and drag Demo User's action into Jane's meeting. After the fix, it
must not. A second check confirms genuine same-person carry-over still works.

Run: cd /app/backend && python3 tests/test_carryover_fix.py
"""
import asyncio
import os
import sys
import uuid
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import asyncpg
from utils.transcription_pipeline import _get_rolled_actions

MANAGER_ID = "465c5101-bbc8-4f26-adaa-c906d3324dd5"   # Demo Manager
DEMO_USER_ID = "831bdaef-14ca-49ed-8fb0-9b8d36bc1ef6"  # Demo User ("Diane")
JANE_ID = "724367a3-1ca9-498b-890b-0516b2f122f5"       # Jane Smith ("Rachel")
ORG_ID = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"


def attendee(uid, name, role):
    return {"user_id": uid, "name": name, "email": "", "role": role, "present": True, "reviewed": False, "reviewed_at": None}


async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], ssl="require")
    now = datetime.now(timezone.utc).isoformat()
    meeting_a = f"test-carryover-a-{uuid.uuid4().hex[:8]}"
    meeting_b = f"test-carryover-b-{uuid.uuid4().hex[:8]}"
    analysis_a = f"test-carryover-analysis-{uuid.uuid4().hex[:8]}"

    attendees_a = [attendee(MANAGER_ID, "Demo Manager", "manager"), attendee(DEMO_USER_ID, "Demo User", "attendee")]
    attendees_b = [attendee(MANAGER_ID, "Demo Manager", "manager"), attendee(JANE_ID, "Jane Smith", "attendee")]

    actions_a = [{"id": "act1", "text": "Follow up on care plan review", "completed": False, "assigned_to": None}]

    try:
        await conn.execute(
            "INSERT INTO analyses (id, actions, risks, cqc_mappings, care_cert_mappings, custom_mappings, achievements, learning_needs, created_at) "
            "VALUES ($1,$2,'[]','[]','[]','[]','[]','[]',$3)",
            analysis_a, json.dumps(actions_a), now,
        )
        # Meeting A: Demo User's meeting, sign_off_manager_id left NULL (the real-world mistake)
        await conn.execute(
            "INSERT INTO meetings (id, org_id, title, date, meeting_type, created_by, created_by_name, "
            "sign_off_manager_id, attendees, status, analysis_id, recording_events, paused_periods, "
            "total_paused_duration_seconds, audio_deletion_status, created_at, updated_at) "
            "VALUES ($1,$2,'Supervision with Demo User','2026-08-01','supervision',$3,'Demo Manager',"
            "NULL,$4,'in_review',$5,'[]','[]',0,'none',$6,$6)",
            meeting_a, ORG_ID, MANAGER_ID, json.dumps(attendees_a), analysis_a, now,
        )
        # Meeting B: Jane's meeting, also sign_off_manager_id NULL
        await conn.execute(
            "INSERT INTO meetings (id, org_id, title, date, meeting_type, created_by, created_by_name, "
            "sign_off_manager_id, attendees, status, recording_events, paused_periods, "
            "total_paused_duration_seconds, audio_deletion_status, created_at, updated_at) "
            "VALUES ($1,$2,'Supervision with Jane Smith','2026-08-02','supervision',$3,'Demo Manager',"
            "NULL,$4,'analyzing','[]','[]',0,'none',$5,$5)",
            meeting_b, ORG_ID, MANAGER_ID, json.dumps(attendees_b), now,
        )

        # TEST 1: manager shared between A and B must NOT cause a false carry-over into B
        rolled_into_b = await _get_rolled_actions(conn, attendees_b, meeting_b, manager_id=None)
        assert rolled_into_b == [], f"FAIL: Demo User's action leaked into Jane's meeting: {rolled_into_b}"
        print("PASS: manager-shared-attendee no longer causes a false carry-over")

        # TEST 2: genuine same-person carry-over still works (Demo User attends a new meeting C)
        meeting_c = f"test-carryover-c-{uuid.uuid4().hex[:8]}"
        attendees_c = [attendee(MANAGER_ID, "Demo Manager", "manager"), attendee(DEMO_USER_ID, "Demo User", "attendee")]
        rolled_into_c = await _get_rolled_actions(conn, attendees_c, meeting_c, manager_id=None)
        # Filter to THIS run's seeded meeting — a concurrent pytest-xdist worker may have
        # seeded its own identical meeting_a for the same Demo User.
        mine = [r for r in rolled_into_c if r["source_meeting_id"] == meeting_a]
        assert len(mine) == 1, f"FAIL: genuine carry-over broke: {rolled_into_c}"
        print("PASS: genuine same-person carry-over still works")

    finally:
        await conn.execute("DELETE FROM meetings WHERE id = ANY($1)", [meeting_a, meeting_b])
        await conn.execute("DELETE FROM analyses WHERE id = $1", analysis_a)
        await conn.close()


def test_carryover_manager_exclusion_and_genuine_rollover():
    """pytest entry point (also runnable directly via `python3 tests/test_carryover_fix.py`)."""
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
