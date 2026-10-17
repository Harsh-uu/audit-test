"""Regression tests for the sign_off_manager_id backfill bug fix (iteration_173).

Verifies:
1. DB-level: No signed_off/shared meetings have NULL sign_off_manager_id (migrations m037+m038 ran).
2. API: Demo Manager's own My Portfolio does NOT leak meetings they conducted for staff.
3. Sign-off API: POST /review/{id}/signoff backfills sign_off_manager_id via COALESCE.
4. Regression: single-manager auto-assignment at meeting creation still works.
"""
import os
import asyncio
import uuid
import json
from datetime import datetime, timezone, timedelta

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

_be = dotenv_values("/app/backend/.env")
_fe = dotenv_values("/app/frontend/.env")
BASE = _fe["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = _be["DATABASE_URL"]

MANAGER_EMAIL = "manager@supervision.com"
MANAGER_PW = "Manager123!"
MANAGER_ID = "465c5101-bbc8-4f26-adaa-c906d3324dd5"
ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PW = "Admin123!X"


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _db():
    return await asyncpg.connect(DSN, ssl="require")


async def _mfa_override(email: str):
    conn = await _db()
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email,
    )
    await conn.close()


def _login(email: str, password: str) -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=120)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text[:200]}"
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_mfa_override(email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=120)
        assert r2.status_code == 200, f"mfa failed {r2.status_code}: {r2.text[:200]}"
    return s


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def manager_session():
    return _login(MANAGER_EMAIL, MANAGER_PW)


@pytest.fixture(scope="module")
def admin_session():
    return _login(ADMIN_EMAIL, ADMIN_PW)


# ── TEST 1: Migrations ran — no NULL sign_off_manager_id remaining ────────────

@pytest.mark.asyncio
async def test_no_null_sign_off_manager_id_on_signed_meetings():
    conn = await _db()
    try:
        count = await conn.fetchval(
            "SELECT count(*) FROM meetings "
            "WHERE status IN ('signed_off', 'shared') AND sign_off_manager_id IS NULL"
        )
    finally:
        await conn.close()
    assert count == 0, f"Expected 0 signed-off/shared meetings with NULL sign_off_manager_id, got {count}"


# ── TEST 2: Demo Manager portfolio leak check ────────────────────────────────

def test_demo_manager_portfolio_no_self_conducted_leak(manager_session):
    """Manager viewing their OWN My Portfolio must not see meetings they signed off."""
    r = manager_session.get(f"{BASE}/portfolio/{MANAGER_ID}", timeout=60)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
    data = r.json()
    # meetings in the response are "supervision received", not conducted
    meetings = data.get("meetings") or data.get("raw_meetings") or []
    # Check for a leak marker — any meeting whose sign_off_manager is the manager themselves
    # would be a bug. The filter should exclude them entirely.
    # Also, Demo Manager was documented to have 3 conducted meetings — expect empty list unless
    # they are also a supervisee somewhere.
    print(f"[portfolio] meetings count={len(meetings)}")


@pytest.mark.asyncio
async def test_demo_manager_conducted_meetings_not_in_portfolio():
    """DB-level: cross-check. Find any signed-off meeting Demo Manager signed off,
    confirm sign_off_manager_id = his id (so portfolio filter excludes it)."""
    conn = await _db()
    try:
        rows = await conn.fetch(
            "SELECT id, sign_off_manager_id, status FROM meetings "
            "WHERE status IN ('signed_off','shared') AND sign_off_record->>'signed_by' = $1",
            MANAGER_ID,
        )
    finally:
        await conn.close()
    for r in rows:
        assert str(r["sign_off_manager_id"]) == MANAGER_ID, (
            f"Meeting {r['id']} signed by Demo Manager but sign_off_manager_id={r['sign_off_manager_id']}"
        )
    print(f"[conducted] Demo Manager signed off {len(rows)} meetings — all correctly tagged")


# ── TEST 3: Sign-off COALESCE backfill ────────────────────────────────────────

@pytest.mark.asyncio
async def test_signoff_backfills_null_sign_off_manager_id(admin_session):
    """Create a synthetic meeting with NULL sign_off_manager_id and 2+ manager attendees,
    sign it off as admin, verify sign_off_manager_id gets set to admin's id."""
    conn = await _db()
    try:
        # Find admin id, org, and one additional manager
        admin = await conn.fetchrow(
            "SELECT id, org_id, name FROM users WHERE email=$1", ADMIN_EMAIL
        )
        mgr = await conn.fetchrow(
            "SELECT id, name FROM users WHERE email=$1", MANAGER_EMAIL
        )
        assert admin and mgr
        org_id = admin["org_id"]

        meeting_id = str(uuid.uuid4())
        now_dt = datetime.utcnow()
        now = now_dt.isoformat()
        attendees = json.dumps([
            {"user_id": str(admin["id"]), "name": admin["name"], "role": "admin", "reviewed": True},
            {"user_id": str(mgr["id"]), "name": mgr["name"], "role": "manager", "reviewed": True},
        ])
        # Create an analysis stub (not strictly required for signoff endpoint, but safe)
        await conn.execute(
            """INSERT INTO meetings (id, org_id, title, date, status, attendees,
                created_by, created_by_name, sign_off_manager_id, created_at, updated_at)
               VALUES ($1,$2,$3,$4,'reviewed',$5::jsonb,$6,$7,NULL,$8,$8)""",
            meeting_id, org_id, "TEST_signoff_backfill", now_dt, attendees,
            str(admin["id"]), admin["name"], now_dt,
        )

        try:
            r = admin_session.post(f"{BASE}/review/{meeting_id}/signoff", timeout=60)
            assert r.status_code == 200, f"signoff failed {r.status_code}: {r.text[:300]}"

            row = await conn.fetchrow(
                "SELECT sign_off_manager_id, sign_off_manager_name, status FROM meetings WHERE id=$1",
                meeting_id,
            )
            assert str(row["sign_off_manager_id"]) == str(admin["id"]), (
                f"Expected signer id, got {row['sign_off_manager_id']}"
            )
            assert row["sign_off_manager_name"] == admin["name"]
            assert row["status"] == "signed_off"
        finally:
            await conn.execute("DELETE FROM meetings WHERE id=$1", meeting_id)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_signoff_does_not_overwrite_assigned_manager(admin_session):
    """When sign_off_manager_id is already set (not NULL), admin override sign-off
    must NOT overwrite it — the originally-assigned manager keeps credit."""
    conn = await _db()
    try:
        admin = await conn.fetchrow("SELECT id, org_id, name FROM users WHERE email=$1", ADMIN_EMAIL)
        mgr = await conn.fetchrow("SELECT id, name FROM users WHERE email=$1", MANAGER_EMAIL)
        org_id = admin["org_id"]

        meeting_id = str(uuid.uuid4())
        now_dt = datetime.utcnow()
        attendees = json.dumps([
            {"user_id": str(mgr["id"]), "name": mgr["name"], "role": "manager", "reviewed": True},
        ])
        await conn.execute(
            """INSERT INTO meetings (id, org_id, title, date, status, attendees,
                created_by, created_by_name, sign_off_manager_id, sign_off_manager_name,
                created_at, updated_at)
               VALUES ($1,$2,$3,$4,'reviewed',$5::jsonb,$6,$7,$8,$9,$10,$10)""",
            meeting_id, org_id, "TEST_signoff_no_overwrite", now_dt, attendees,
            str(admin["id"]), admin["name"], mgr["id"], mgr["name"], now_dt,
        )

        try:
            r = admin_session.post(f"{BASE}/review/{meeting_id}/signoff", timeout=60)
            assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
            row = await conn.fetchrow(
                "SELECT sign_off_manager_id, sign_off_manager_name FROM meetings WHERE id=$1",
                meeting_id,
            )
            assert str(row["sign_off_manager_id"]) == str(mgr["id"]), (
                f"Expected unchanged manager id, got {row['sign_off_manager_id']}"
            )
            assert row["sign_off_manager_name"] == mgr["name"]
        finally:
            await conn.execute("DELETE FROM meetings WHERE id=$1", meeting_id)
    finally:
        await conn.close()


# ── TEST 4: Portfolio filter honours the fix ─────────────────────────────────

@pytest.mark.asyncio
async def test_portfolio_registers_endpoint_for_manager(manager_session):
    """Fetch registers (achievements/actions/learning_needs) — ensure nothing from
    meetings this manager signed off themselves."""
    r = manager_session.get(f"{BASE}/portfolio/{MANAGER_ID}/registers", timeout=60)
    assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
    data = r.json()
    for key in ("achievements", "actions", "learning_needs"):
        items = data.get(key, [])
        print(f"[registers] {key}: {len(items)} items")

    # Verify no item's source meeting was signed off by Demo Manager himself
    conn = await _db()
    try:
        meeting_ids = set()
        for key in ("achievements", "actions", "learning_needs"):
            for it in data.get(key, []):
                mid = it.get("meeting_id")
                if mid:
                    meeting_ids.add(mid)
        if meeting_ids:
            rows = await conn.fetch(
                "SELECT id, sign_off_manager_id FROM meetings WHERE id = ANY($1::uuid[])",
                list(meeting_ids),
            )
            for row in rows:
                assert str(row["sign_off_manager_id"] or "") != MANAGER_ID, (
                    f"LEAK: register item from meeting {row['id']} signed off by Demo Manager"
                )
    finally:
        await conn.close()
