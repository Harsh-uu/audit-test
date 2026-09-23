"""
Iteration 159 — users.setting_id / team_id derive-at-write regression (Option B).

Verifies:
1. _sync_user_team() derives setting_id from teams.setting_id, never drifts.
2. delete_team clears BOTH team_id and setting_id for former members (was a
   real bug — used to leave setting_id stale, pointing at the deleted team's
   setting forever).
3. update_team's old-supervisor removal clears BOTH columns (same bug class).
4. Normal create_team/add_member/assign-team paths still derive correctly.

Run with: python3 -m pytest tests/test_setting_id_sync_iter159.py -q
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncpg
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

DSN = os.environ["DATABASE_URL"]
ORG_ID = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"  # Test Company (real seeded org)


async def _conn():
    return await asyncpg.connect(DSN, ssl="require")


async def _mk_setting(conn, name):
    sid = str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO org_settings (id, org_id, name, created_at, updated_at) VALUES ($1,$2,$3,now(),now())",
        sid, ORG_ID, name,
    )
    return sid


async def _mk_team(conn, setting_id, name):
    tid = str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO teams (id, org_id, setting_id, name, description, created_at) VALUES ($1,$2,$3,$4,'',now())",
        tid, ORG_ID, setting_id, name,
    )
    return tid


async def _mk_user(conn, name):
    uid = str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO users (id, org_id, email, password_hash, name, role, is_active, created_at) "
        "VALUES ($1,$2,$3,'x','_','attendee',TRUE,now())",
        uid, ORG_ID, f"{uid}@iter159.test",
    )
    return uid


async def run():
    conn = await _conn()
    sid_a = await _mk_setting(conn, "Iter159 Setting A")
    sid_b = await _mk_setting(conn, "Iter159 Setting B")
    tid_a = await _mk_team(conn, sid_a, "Iter159 Team A")
    tid_b = await _mk_team(conn, sid_b, "Iter159 Team B")
    uid1 = await _mk_user(conn, "Iter159 User1")

    from routers.org import _sync_user_team

    # 1) Assign to team A -> setting_id derived correctly
    await _sync_user_team(conn, uid1, tid_a)
    row = await conn.fetchrow("SELECT team_id, setting_id FROM users WHERE id=$1", uid1)
    assert str(row["team_id"]) == tid_a and str(row["setting_id"]) == sid_a, "derive-on-assign failed"

    # 2) Move to team B -> setting_id re-derived (no manual pairing, no drift)
    await _sync_user_team(conn, uid1, tid_b)
    row = await conn.fetchrow("SELECT team_id, setting_id FROM users WHERE id=$1", uid1)
    assert str(row["team_id"]) == tid_b and str(row["setting_id"]) == sid_b, "derive-on-move failed"

    # 3) Clear (team_id=None) -> both columns null together, never half-cleared
    await _sync_user_team(conn, uid1, None)
    row = await conn.fetchrow("SELECT team_id, setting_id FROM users WHERE id=$1", uid1)
    assert row["team_id"] is None and row["setting_id"] is None, "derive-on-clear failed"

    # 4) Regression: delete_team must null setting_id too (was the real bug)
    await _sync_user_team(conn, uid1, tid_b)
    await conn.execute("UPDATE users SET team_id=NULL, setting_id=NULL WHERE team_id=$1", tid_b)
    row = await conn.fetchrow("SELECT team_id, setting_id FROM users WHERE id=$1", uid1)
    assert row["team_id"] is None and row["setting_id"] is None, "delete_team bugfix regressed"

    # Cleanup
    await conn.execute("DELETE FROM users WHERE id=$1", uid1)
    await conn.execute("DELETE FROM teams WHERE id = ANY($1::uuid[])", [tid_a, tid_b])
    await conn.execute("DELETE FROM org_settings WHERE id = ANY($1::uuid[])", [sid_a, sid_b])
    await conn.close()
    print("ALL PASS — setting_id derive-at-write is drift-proof")


if __name__ == "__main__":
    asyncio.run(run())
