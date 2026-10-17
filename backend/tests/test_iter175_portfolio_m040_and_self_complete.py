"""Iteration 175 regression tests:

1. m040 migration: backfills sign_off_manager_id on ANY-status meetings
   that have exactly one manager/admin attendee (not just signed_off/shared).
   Ambiguous (2+ mgr-role attendees) must be left NULL.

2. review.py self-completion permission fix:
   - PATCH /review/{meeting_id}/actions/{action_id} — assignee can self-toggle (200)
     non-assignee gets 403; manager/admin override still works (200).
   - PATCH /review/{meeting_id}/learning_needs/{ln_id} (NEW endpoint) — same semantics.
"""
import os
import asyncio
import uuid
import json
from datetime import datetime, timezone, timedelta

import asyncpg
import bcrypt
import pytest
import pytest_asyncio
import requests
from dotenv import dotenv_values

_be = dotenv_values("/app/backend/.env")
_fe = dotenv_values("/app/frontend/.env")
BASE = _fe["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = _be["DATABASE_URL"]

ADMIN_EMAIL = "admin@supervision.com";  ADMIN_PW = "Admin123!X"
MANAGER_EMAIL = "manager@supervision.com"; MANAGER_PW = "Manager123!"
STAFF_EMAIL = "user@supervision.com"; STAFF_PW = "Staff123!"
JANE_EMAIL = "jane@supervision.com"; JANE_PW = "JaneNew456!"


async def _db():
    return await asyncpg.connect(DSN, ssl="require")


async def _mfa_override(email: str):
    conn = await _db()
    try:
        h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
        exp = datetime.now(timezone.utc) + timedelta(minutes=10)
        await conn.execute(
            "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
            h, exp, email,
        )
    finally:
        await conn.close()


def _login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=120)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_mfa_override(email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=120)
        assert r2.status_code == 200, f"mfa {email}: {r2.status_code} {r2.text[:200]}"
    return s


@pytest.fixture(scope="module")
def admin_session(): return _login(ADMIN_EMAIL, ADMIN_PW)
@pytest.fixture(scope="module")
def manager_session(): return _login(MANAGER_EMAIL, MANAGER_PW)
@pytest.fixture(scope="module")
def staff_session(): return _login(STAFF_EMAIL, STAFF_PW)
@pytest.fixture(scope="module")
def jane_session(): return _login(JANE_EMAIL, JANE_PW)


# ─────────────────────────────────────────────────────────────────────────────
# m040 tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_m040_in_schema_migrations_ledger():
    conn = await _db()
    try:
        row = await conn.fetchrow(
            "SELECT version FROM schema_migrations WHERE version=$1",
            "040_backfill_sign_off_manager_id_any_status",
        )
    finally:
        await conn.close()
    assert row is not None, "m040 not in ledger"


@pytest.mark.asyncio
async def test_m040_backfills_non_signoff_status_with_single_manager():
    """Construct a reviewed-status meeting (not signed_off), NULL
    sign_off_manager_id, exactly one manager-role attendee + an analysis.
    Re-running m040 SQL must backfill it to that manager's id."""
    from migrations.m040_backfill_sign_off_manager_id_any_status import SQL
    conn = await _db()
    created_meeting = None
    created_analysis = None
    try:
        admin = await conn.fetchrow("SELECT id, org_id FROM users WHERE email=$1", ADMIN_EMAIL)
        mgr = await conn.fetchrow("SELECT id, name FROM users WHERE email=$1", MANAGER_EMAIL)
        org_id = admin["org_id"]

        # Create meeting first (NULL analysis_id), then analysis with meeting_id, then wire
        analysis_id = str(uuid.uuid4())
        created_analysis = analysis_id
        now_dt = datetime.now(timezone.utc)

        meeting_id = str(uuid.uuid4())
        created_meeting = meeting_id
        attendees = json.dumps([
            {"user_id": str(mgr["id"]), "name": mgr["name"], "role": "manager"},
        ])
        await conn.execute(
            """INSERT INTO meetings (id, org_id, title, date, status, attendees, analysis_id,
                created_by, created_by_name, sign_off_manager_id, created_at, updated_at)
               VALUES ($1,$2,'TEST_m040_single_mgr_reviewed',$3::timestamptz,'reviewed',$4::jsonb,NULL,
                       $5,$6,NULL,$3::timestamptz,$3::timestamptz)""",
            meeting_id, org_id, now_dt, attendees, str(admin["id"]), "Admin",
        )
        await conn.execute(
            """INSERT INTO analyses (id, meeting_id, org_id, actions, learning_needs, achievements, created_at)
               VALUES ($1,$2,$3,'[]'::jsonb,'[]'::jsonb,'[]'::jsonb,$4::timestamptz)""",
            analysis_id, meeting_id, org_id, now_dt,
        )
        await conn.execute("UPDATE meetings SET analysis_id=$1 WHERE id=$2", analysis_id, meeting_id)

        await conn.execute(SQL)

        row = await conn.fetchrow(
            "SELECT sign_off_manager_id, sign_off_manager_name, status FROM meetings WHERE id=$1",
            meeting_id,
        )
        assert row["status"] == "reviewed", "status should remain unchanged"
        assert str(row["sign_off_manager_id"]) == str(mgr["id"]), (
            f"expected backfill to manager {mgr['id']}, got {row['sign_off_manager_id']}"
        )
        assert row["sign_off_manager_name"] == mgr["name"]
    finally:
        if created_meeting:
            await conn.execute("DELETE FROM meetings WHERE id=$1", created_meeting)
        if created_analysis:
            await conn.execute("DELETE FROM analyses WHERE id=$1", created_analysis)
        await conn.close()


@pytest.mark.asyncio
async def test_m040_leaves_ambiguous_meeting_null():
    """2+ manager-role attendees + NULL sign_off_manager_id = must stay NULL."""
    from migrations.m040_backfill_sign_off_manager_id_any_status import SQL
    conn = await _db()
    created_meeting = None
    created_analysis = None
    try:
        admin = await conn.fetchrow("SELECT id, org_id FROM users WHERE email=$1", ADMIN_EMAIL)
        mgrs = await conn.fetch(
            "SELECT id, name FROM users WHERE org_id=$1 AND role='manager' AND id<>$2 LIMIT 2",
            admin["org_id"], admin["id"],
        )
        if len(mgrs) < 2:
            pytest.skip("Need 2+ non-admin managers in admin's org")
        org_id = admin["org_id"]

        analysis_id = str(uuid.uuid4())
        created_analysis = analysis_id
        now_dt = datetime.now(timezone.utc)

        meeting_id = str(uuid.uuid4())
        created_meeting = meeting_id
        attendees = json.dumps([
            {"user_id": str(mgrs[0]["id"]), "name": mgrs[0]["name"], "role": "manager"},
            {"user_id": str(mgrs[1]["id"]), "name": mgrs[1]["name"], "role": "manager"},
        ])
        await conn.execute(
            """INSERT INTO meetings (id, org_id, title, date, status, attendees, analysis_id,
                created_by, created_by_name, sign_off_manager_id, created_at, updated_at)
               VALUES ($1,$2,'TEST_m040_ambiguous_inreview',$3::timestamptz,'in_review',$4::jsonb,NULL,
                       $5,$6,NULL,$3::timestamptz,$3::timestamptz)""",
            meeting_id, org_id, now_dt, attendees, str(admin["id"]), "Admin",
        )
        await conn.execute(
            """INSERT INTO analyses (id, meeting_id, org_id, actions, learning_needs, achievements, created_at)
               VALUES ($1,$2,$3,'[]'::jsonb,'[]'::jsonb,'[]'::jsonb,$4::timestamptz)""",
            analysis_id, meeting_id, org_id, now_dt,
        )
        await conn.execute("UPDATE meetings SET analysis_id=$1 WHERE id=$2", analysis_id, meeting_id)

        await conn.execute(SQL)

        row = await conn.fetchrow(
            "SELECT sign_off_manager_id FROM meetings WHERE id=$1", meeting_id
        )
        assert row["sign_off_manager_id"] is None, (
            f"Ambiguous meeting should stay NULL, got {row['sign_off_manager_id']}"
        )
    finally:
        if created_meeting:
            await conn.execute("DELETE FROM meetings WHERE id=$1", created_meeting)
        if created_analysis:
            await conn.execute("DELETE FROM analyses WHERE id=$1", created_analysis)
        await conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Self-completion permission tests (actions + learning_needs on review router)
# ─────────────────────────────────────────────────────────────────────────────

async def _get_user_id(email):
    conn = await _db()
    try:
        return await conn.fetchval("SELECT id FROM users WHERE email=$1", email)
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def seeded_meeting_with_items():
    """Create a meeting+analysis with:
    - 1 action assigned to STAFF_EMAIL (user@supervision.com)
    - 1 learning need assigned to STAFF_EMAIL
    Yield (meeting_id, action_id, ln_id). Clean up after.
    """
    conn = await _db()
    created_meeting = None
    created_analysis = None
    try:
        admin = await conn.fetchrow("SELECT id, org_id FROM users WHERE email=$1", ADMIN_EMAIL)
        staff_id = await conn.fetchval("SELECT id FROM users WHERE email=$1", STAFF_EMAIL)
        mgr = await conn.fetchrow("SELECT id, name FROM users WHERE email=$1", MANAGER_EMAIL)
        org_id = admin["org_id"]

        action_id = str(uuid.uuid4())
        ln_id = str(uuid.uuid4())
        actions = [{
            "id": action_id, "text": "TEST iter175 action", "action": "TEST iter175 action",
            "assigned_to_user_id": str(staff_id), "assigned_to": "user@supervision.com",
            "completed": False,
        }]
        lns = [{
            "id": ln_id, "text": "TEST iter175 learning need",
            "assigned_to_user_id": str(staff_id), "assigned_to": "user@supervision.com",
            "completed": False,
        }]

        analysis_id = str(uuid.uuid4())
        created_analysis = analysis_id
        now_dt = datetime.now(timezone.utc)

        meeting_id = str(uuid.uuid4())
        created_meeting = meeting_id
        attendees = json.dumps([
            {"user_id": str(mgr["id"]), "name": mgr["name"], "role": "manager"},
            {"user_id": str(staff_id), "name": "Staff", "role": "attendee"},
        ])
        await conn.execute(
            """INSERT INTO meetings (id, org_id, title, date, status, attendees, analysis_id,
                created_by, created_by_name, sign_off_manager_id, sign_off_manager_name,
                created_at, updated_at)
               VALUES ($1,$2,'TEST iter175 meeting',$3::timestamptz,'reviewed',$4::jsonb,NULL,
                       $5,$6,$7,$8,$3::timestamptz,$3::timestamptz)""",
            meeting_id, org_id, now_dt, attendees,
            str(mgr["id"]), mgr["name"], mgr["id"], mgr["name"],
        )
        await conn.execute(
            """INSERT INTO analyses (id, meeting_id, org_id, actions, learning_needs, achievements, created_at)
               VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,'[]'::jsonb,$6::timestamptz)""",
            analysis_id, meeting_id, org_id, json.dumps(actions), json.dumps(lns), now_dt,
        )
        await conn.execute("UPDATE meetings SET analysis_id=$1 WHERE id=$2", analysis_id, meeting_id)

        yield meeting_id, action_id, ln_id
    finally:
        if created_meeting:
            await conn.execute("DELETE FROM meetings WHERE id=$1", created_meeting)
        if created_analysis:
            await conn.execute("DELETE FROM analyses WHERE id=$1", created_analysis)
        await conn.close()


@pytest.mark.asyncio
async def test_assignee_can_self_complete_action(staff_session, seeded_meeting_with_items):
    meeting_id, action_id, _ = seeded_meeting_with_items
    r = staff_session.patch(
        f"{BASE}/review/{meeting_id}/actions/{action_id}",
        json={"completed": True}, timeout=30,
    )
    assert r.status_code == 200, f"assignee self-complete action: {r.status_code} {r.text[:200]}"
    assert r.json().get("completed") is True


@pytest.mark.asyncio
async def test_non_assignee_blocked_from_action(jane_session, seeded_meeting_with_items):
    meeting_id, action_id, _ = seeded_meeting_with_items
    r = jane_session.patch(
        f"{BASE}/review/{meeting_id}/actions/{action_id}",
        json={"completed": True}, timeout=30,
    )
    # Jane isn't an attendee of the meeting, so could hit 404 (meeting invisible) or 403.
    # Either way she must NOT get 200.
    assert r.status_code in (403, 404), f"non-assignee action: {r.status_code} {r.text[:200]}"


@pytest.mark.asyncio
async def test_manager_can_override_action(manager_session, seeded_meeting_with_items):
    meeting_id, action_id, _ = seeded_meeting_with_items
    r = manager_session.patch(
        f"{BASE}/review/{meeting_id}/actions/{action_id}",
        json={"completed": True}, timeout=30,
    )
    assert r.status_code == 200, f"manager override action: {r.status_code} {r.text[:200]}"


@pytest.mark.asyncio
async def test_assignee_can_self_complete_learning_need(staff_session, seeded_meeting_with_items):
    meeting_id, _, ln_id = seeded_meeting_with_items
    r = staff_session.patch(
        f"{BASE}/review/{meeting_id}/learning_needs/{ln_id}",
        json={"completed": True}, timeout=30,
    )
    assert r.status_code == 200, f"assignee self-complete LN: {r.status_code} {r.text[:200]}"
    assert r.json().get("completed") is True


@pytest.mark.asyncio
async def test_non_assignee_blocked_from_learning_need(jane_session, seeded_meeting_with_items):
    meeting_id, _, ln_id = seeded_meeting_with_items
    r = jane_session.patch(
        f"{BASE}/review/{meeting_id}/learning_needs/{ln_id}",
        json={"completed": True}, timeout=30,
    )
    assert r.status_code in (403, 404), f"non-assignee LN: {r.status_code} {r.text[:200]}"


@pytest.mark.asyncio
async def test_manager_can_override_learning_need(manager_session, seeded_meeting_with_items):
    meeting_id, _, ln_id = seeded_meeting_with_items
    r = manager_session.patch(
        f"{BASE}/review/{meeting_id}/learning_needs/{ln_id}",
        json={"completed": True}, timeout=30,
    )
    assert r.status_code == 200, f"manager override LN: {r.status_code} {r.text[:200]}"
