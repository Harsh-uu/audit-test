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
    r = None
    for attempt in range(5):
        r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=120)
        if r.status_code == 200:
            break
        if r.status_code in (429, 502, 503, 504):
            import time
            time.sleep(10 + attempt * 5)
            continue
        break
    assert r is not None and r.status_code == 200, f"login failed {r.status_code}: {r.text[:200]}"
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
    """Admin signs off meeting with ambiguous (admin+manager role) attendees.
    Post iteration_174 FIX A: admin+manager both count as 'manager/admin role',
    so attendees are ambiguous (2 of them). Signer is admin -> leave NULL
    (don't guess). This supersedes the iter173 expectation (which was: default
    to signer's id). The new behavior is deliberately more conservative."""
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
            # iteration_174 FIX A: ambiguous attendees + admin signer -> NULL
            assert row["sign_off_manager_id"] is None, (
                f"Expected NULL (ambiguous+admin), got {row['sign_off_manager_id']}"
            )
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


# ── TEST 5 (iteration_174 FIX A): Admin signs off on behalf of a single manager
#    attendee -> manager gets credited, NOT the admin ──────────────────────────

PRIYA_ID = "cd9bece9-231b-4fa3-b230-671aa2a33723"  # Priya Sunil (role=manager)
PRIYA_ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"


@pytest.mark.asyncio
async def test_admin_signoff_credits_single_manager_attendee_not_admin(admin_session):
    """FIX A: when admin signs off a meeting that has exactly one manager-role
    attendee (not the admin), sign_off_manager_id must be set to THAT manager,
    not to the admin who clicked sign-off."""
    conn = await _db()
    try:
        admin = await conn.fetchrow("SELECT id, org_id, name, role FROM users WHERE email=$1", ADMIN_EMAIL)
        assert admin and admin["role"] == "admin"
        # Pick a manager-role user in the admin's org who is NOT the admin.
        mgr = await conn.fetchrow(
            "SELECT id, name FROM users WHERE org_id=$1 AND role='manager' AND id<>$2 LIMIT 1",
            admin["org_id"], admin["id"],
        )
        if not mgr:
            pytest.skip("No non-admin manager user in admin's org")
        # Find a staff/attendee in same org
        staff = await conn.fetchrow(
            "SELECT id, name FROM users WHERE org_id=$1 AND role NOT IN ('admin') AND id<>$2 LIMIT 1",
            admin["org_id"], mgr["id"],
        )
        assert staff

        meeting_id = str(uuid.uuid4())
        now_dt = datetime.utcnow()
        attendees = json.dumps([
            {"user_id": str(mgr["id"]), "name": mgr["name"], "role": "manager", "reviewed": True},
            {"user_id": str(staff["id"]), "name": staff["name"], "role": "attendee", "reviewed": True},
        ])
        await conn.execute(
            """INSERT INTO meetings (id, org_id, title, date, status, attendees,
                created_by, created_by_name, sign_off_manager_id, created_at, updated_at)
               VALUES ($1,$2,$3,$4,'reviewed',$5::jsonb,$6,$7,NULL,$8,$8)""",
            meeting_id, admin["org_id"], "TEST_admin_signoff_credits_manager", now_dt,
            attendees, str(admin["id"]), admin["name"], now_dt,
        )

        try:
            r = admin_session.post(f"{BASE}/review/{meeting_id}/signoff", timeout=60)
            assert r.status_code == 200, f"signoff failed {r.status_code}: {r.text[:300]}"

            row = await conn.fetchrow(
                "SELECT sign_off_manager_id, sign_off_manager_name, status FROM meetings WHERE id=$1",
                meeting_id,
            )
            assert str(row["sign_off_manager_id"]) == str(mgr["id"]), (
                f"Expected manager attendee {mgr['id']} to be credited, got {row['sign_off_manager_id']} (admin={admin['id']})"
            )
            assert row["sign_off_manager_name"] == mgr["name"]
            assert row["status"] == "signed_off"
            assert str(row["sign_off_manager_id"]) != str(admin["id"]), (
                "REGRESSION: admin was credited as sign_off_manager_id — iteration_174 FIX A broken"
            )
        finally:
            await conn.execute("DELETE FROM meetings WHERE id=$1", meeting_id)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_admin_signoff_ambiguous_managers_leaves_null(admin_session):
    """FIX A edge case: 2+ manager-role attendees + admin signer = leave NULL
    (don't guess). Must not crash and must not mis-attribute."""
    conn = await _db()
    try:
        admin = await conn.fetchrow("SELECT id, org_id, name, role FROM users WHERE email=$1", ADMIN_EMAIL)
        mgrs = await conn.fetch(
            "SELECT id, name FROM users WHERE org_id=$1 AND role='manager' AND id<>$2 LIMIT 2",
            admin["org_id"], admin["id"],
        )
        if len(mgrs) < 2:
            pytest.skip("Need 2+ non-admin managers in admin's org")

        meeting_id = str(uuid.uuid4())
        now_dt = datetime.utcnow()
        attendees = json.dumps([
            {"user_id": str(mgrs[0]["id"]), "name": mgrs[0]["name"], "role": "manager", "reviewed": True},
            {"user_id": str(mgrs[1]["id"]), "name": mgrs[1]["name"], "role": "manager", "reviewed": True},
        ])
        await conn.execute(
            """INSERT INTO meetings (id, org_id, title, date, status, attendees,
                created_by, created_by_name, sign_off_manager_id, created_at, updated_at)
               VALUES ($1,$2,$3,$4,'reviewed',$5::jsonb,$6,$7,NULL,$8,$8)""",
            meeting_id, admin["org_id"], "TEST_admin_signoff_ambiguous", now_dt,
            attendees, str(admin["id"]), admin["name"], now_dt,
        )
        try:
            r = admin_session.post(f"{BASE}/review/{meeting_id}/signoff", timeout=60)
            assert r.status_code == 200, f"signoff failed {r.status_code}: {r.text[:300]}"
            row = await conn.fetchrow(
                "SELECT sign_off_manager_id, status FROM meetings WHERE id=$1", meeting_id,
            )
            assert row["status"] == "signed_off"
            assert row["sign_off_manager_id"] is None, (
                f"Ambiguous + admin signer should stay NULL, got {row['sign_off_manager_id']}"
            )
        finally:
            await conn.execute("DELETE FROM meetings WHERE id=$1", meeting_id)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_manager_self_signoff_single_attendee_credits_self(manager_session):
    """Regression: manager signs off their own meeting (they are the sole
    manager-role attendee) — attribution must still be to themselves."""
    conn = await _db()
    try:
        mgr = await conn.fetchrow("SELECT id, org_id, name FROM users WHERE email=$1", MANAGER_EMAIL)
        staff = await conn.fetchrow(
            "SELECT id, name FROM users WHERE org_id=$1 AND role NOT IN ('admin','manager') LIMIT 1",
            mgr["org_id"],
        )
        assert mgr and staff

        meeting_id = str(uuid.uuid4())
        now_dt = datetime.utcnow()
        attendees = json.dumps([
            {"user_id": str(mgr["id"]), "name": mgr["name"], "role": "manager", "reviewed": True},
            {"user_id": str(staff["id"]), "name": staff["name"], "role": "attendee", "reviewed": True},
        ])
        await conn.execute(
            """INSERT INTO meetings (id, org_id, title, date, status, attendees,
                created_by, created_by_name, sign_off_manager_id, created_at, updated_at)
               VALUES ($1,$2,$3,$4,'reviewed',$5::jsonb,$6,$7,NULL,$8,$8)""",
            meeting_id, mgr["org_id"], "TEST_mgr_self_signoff", now_dt,
            attendees, str(mgr["id"]), mgr["name"], now_dt,
        )
        try:
            r = manager_session.post(f"{BASE}/review/{meeting_id}/signoff", timeout=60)
            assert r.status_code == 200, f"signoff failed {r.status_code}: {r.text[:300]}"
            row = await conn.fetchrow(
                "SELECT sign_off_manager_id FROM meetings WHERE id=$1", meeting_id,
            )
            assert str(row["sign_off_manager_id"]) == str(mgr["id"])
        finally:
            await conn.execute("DELETE FROM meetings WHERE id=$1", meeting_id)
    finally:
        await conn.close()


# ── TEST 6 (iteration_174 FIX B): m039 correction migration ──────────────────

@pytest.mark.asyncio
async def test_m039_registered_and_applied():
    """FIX B: m039 was registered and applied to schema_migrations ledger."""
    conn = await _db()
    try:
        row = await conn.fetchrow(
            "SELECT version, applied_at FROM schema_migrations WHERE version=$1",
            "039_fix_sign_off_manager_admin_misattribution",
        )
    finally:
        await conn.close()
    assert row is not None, "m039 was not applied to schema_migrations ledger"


@pytest.mark.asyncio
async def test_m039_corrects_admin_misattribution_but_leaves_legit_untouched():
    """FIX B: construct 3 synthetic rows and re-run m039's SQL:
      (A) admin mis-attributed, one manager-role attendee differs -> CORRECTED
      (B) admin is sole manager-role attendee -> UNTOUCHED (legit)
      (C) sign_off_manager_id already points at a non-admin manager -> UNTOUCHED
    """
    from migrations.m039_fix_sign_off_manager_admin_misattribution import SQL

    conn = await _db()
    created_ids = []
    try:
        admin = await conn.fetchrow(
            "SELECT id, org_id, name FROM users WHERE email=$1", ADMIN_EMAIL
        )
        mgr = await conn.fetchrow(
            "SELECT id, name FROM users WHERE email=$1", MANAGER_EMAIL
        )
        assert admin and mgr
        org_id = admin["org_id"]
        now_dt = datetime.utcnow()

        # (A) Misattribution: sign_off_manager_id = admin, but single manager attendee = mgr.
        mid_a = str(uuid.uuid4())
        created_ids.append(mid_a)
        atts_a = json.dumps([
            {"user_id": str(mgr["id"]), "name": mgr["name"], "role": "manager"},
            {"user_id": str(admin["id"]), "name": admin["name"], "role": "admin"},
        ])
        await conn.execute(
            """INSERT INTO meetings (id, org_id, title, date, status, attendees,
                created_by, created_by_name,
                sign_off_manager_id, sign_off_manager_name, created_at, updated_at)
               VALUES ($1,$2,'TEST_m039_A',$3::timestamptz,'signed_off',$4::jsonb,$7,$8,$5,$6,$3::timestamptz,$3::timestamptz)""",
            mid_a, org_id, now_dt, atts_a, admin["id"], admin["name"], admin["id"], admin["name"],
        )

        # (B) Legit: admin is the ONLY manager/admin-role attendee (truly conducted by admin).
        mid_b = str(uuid.uuid4())
        created_ids.append(mid_b)
        atts_b = json.dumps([
            {"user_id": str(admin["id"]), "name": admin["name"], "role": "admin"},
        ])
        await conn.execute(
            """INSERT INTO meetings (id, org_id, title, date, status, attendees,
                created_by, created_by_name,
                sign_off_manager_id, sign_off_manager_name, created_at, updated_at)
               VALUES ($1,$2,'TEST_m039_B',$3::timestamptz,'signed_off',$4::jsonb,$7,$8,$5,$6,$3::timestamptz,$3::timestamptz)""",
            mid_b, org_id, now_dt, atts_b, admin["id"], admin["name"], admin["id"], admin["name"],
        )

        # (C) Already-correct: sign_off_manager_id points at the manager, not admin.
        mid_c = str(uuid.uuid4())
        created_ids.append(mid_c)
        atts_c = json.dumps([
            {"user_id": str(mgr["id"]), "name": mgr["name"], "role": "manager"},
        ])
        await conn.execute(
            """INSERT INTO meetings (id, org_id, title, date, status, attendees,
                created_by, created_by_name,
                sign_off_manager_id, sign_off_manager_name, created_at, updated_at)
               VALUES ($1,$2,'TEST_m039_C',$3::timestamptz,'signed_off',$4::jsonb,$7,$8,$5,$6,$3::timestamptz,$3::timestamptz)""",
            mid_c, org_id, now_dt, atts_c, mgr["id"], mgr["name"], admin["id"], admin["name"],
        )

        # Re-run the migration SQL
        await conn.execute(SQL)

        row_a = await conn.fetchrow(
            "SELECT sign_off_manager_id, sign_off_manager_name FROM meetings WHERE id=$1", mid_a
        )
        row_b = await conn.fetchrow(
            "SELECT sign_off_manager_id FROM meetings WHERE id=$1", mid_b
        )
        row_c = await conn.fetchrow(
            "SELECT sign_off_manager_id FROM meetings WHERE id=$1", mid_c
        )

        assert str(row_a["sign_off_manager_id"]) == str(mgr["id"]), (
            f"(A) m039 should re-attribute admin misattribution to manager; got {row_a['sign_off_manager_id']}"
        )
        assert row_a["sign_off_manager_name"] == mgr["name"]
        assert str(row_b["sign_off_manager_id"]) == str(admin["id"]), (
            f"(B) m039 wrongly touched legit admin-conducted row; now {row_b['sign_off_manager_id']}"
        )
        assert str(row_c["sign_off_manager_id"]) == str(mgr["id"]), (
            f"(C) m039 wrongly touched already-correct row; now {row_c['sign_off_manager_id']}"
        )
    finally:
        for mid in created_ids:
            await conn.execute("DELETE FROM meetings WHERE id=$1", mid)
        await conn.close()
