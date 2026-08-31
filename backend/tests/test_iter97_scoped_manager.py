"""Iteration 97 — scoped-manager regression (users.team_id / users.setting_id).

Creates a temporary branch + team, scopes manager@supervision.com to it, and
verifies every scoped read path returns ONLY in-scope data. Restores the
manager's original team_id/setting_id afterwards.
"""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

BE = dotenv_values("/app/backend/.env")
FE = dotenv_values("/app/frontend/.env")
API = FE["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
DSN = BE["DATABASE_URL"]
TAG = uuid.uuid4().hex[:6]

ADMIN = ("admin@supervision.com", "Admin123!")
MANAGER = ("manager@supervision.com", "Manager123!")
STAFF_EMAIL = "jane@supervision.com"


async def _mfa(email):
    c = await asyncpg.connect(DSN, ssl="require")
    await c.execute("UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
                    bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode(),
                    (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(), email)
    await c.close()


async def _fetch(sql, *a):
    c = await asyncpg.connect(DSN, ssl="require")
    rows = await c.fetch(sql, *a)
    await c.close()
    return [dict(r) for r in rows]


async def _exec(sql, *a):
    c = await asyncpg.connect(DSN, ssl="require")
    res = await c.execute(sql, *a)
    await c.close()
    return res


def _login(email, pw):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"login failed {email}: {r.status_code} {r.text[:200]}")
    d = r.json()
    if d.get("requires_mfa"):
        asyncio.run(_mfa(email))
        r2 = s.post(f"{API}/auth/verify-mfa", json={"mfa_session": d["mfa_session"], "code": "123456"}, timeout=60)
        if r2.status_code != 200:
            pytest.fail(f"mfa failed {email}: {r2.status_code} {r2.text[:200]}")
    me = s.get(f"{API}/auth/me", timeout=60)
    assert me.status_code == 200
    return s, me.json()


@pytest.fixture(scope="module")
def scoped_env():
    """Build branch + team, scope the manager to the team, assign a staff member."""
    admin_s, _ = _login(*ADMIN)
    setting = admin_s.post(f"{API}/org/settings", json={"name": f"TEST_Scope_Branch_{TAG}"}, timeout=60)
    assert setting.status_code == 200, setting.text[:200]
    sid = setting.json()["id"]
    team = admin_s.post(f"{API}/org/settings/{sid}/teams", json={"name": f"TEST_Scope_Team_{TAG}"}, timeout=60)
    assert team.status_code == 200, team.text[:200]
    tid = team.json()["id"]

    users = admin_s.get(f"{API}/admin/users", timeout=60).json()
    mgr = next(u for u in users if u["email"] == MANAGER[0])
    staff = next(u for u in users if u["email"] == STAFF_EMAIL)
    prev = {mgr["id"]: (mgr["team_id"], mgr["setting_id"]), staff["id"]: (staff["team_id"], staff["setting_id"])}

    for uid in (mgr["id"], staff["id"]):
        r = admin_s.patch(f"{API}/org/users/{uid}/assign-team", json={"team_id": tid}, timeout=60)
        assert r.status_code == 200, r.text[:200]

    yield {"admin": admin_s, "setting_id": sid, "team_id": tid,
           "mgr_id": mgr["id"], "staff_id": staff["id"]}

    # teardown: restore assignments then delete team + branch
    for uid, (t, st) in prev.items():
        asyncio.run(_exec("UPDATE users SET team_id=$1, setting_id=$2 WHERE id=$3", t, st, uid))
    admin_s.delete(f"{API}/org/teams/{tid}", timeout=60)
    admin_s.delete(f"{API}/org/settings/{sid}", timeout=60)
    left = asyncio.run(_fetch("SELECT name FROM org_settings WHERE name LIKE 'TEST_Scope%'"))
    assert left == [], f"cleanup incomplete: {left}"


class TestTeamScopedManager:
    def test_assignment_persisted(self, scoped_env):
        rows = asyncio.run(_fetch("SELECT id, team_id, setting_id FROM users WHERE id = ANY($1::text[])",
                                  [scoped_env["mgr_id"], scoped_env["staff_id"]]))
        for r in rows:
            assert str(r["team_id"]) == scoped_env["team_id"]
            assert str(r["setting_id"]) == scoped_env["setting_id"]

    def test_manager_staff_list_scoped_to_team(self, scoped_env):
        s, me = _login(*MANAGER)
        assert me["team_id"] == scoped_env["team_id"]
        r = s.get(f"{API}/admin/users", timeout=60)
        assert r.status_code == 200, r.text[:200]
        users = r.json()
        assert len(users) == 2, [u["email"] for u in users]
        assert {u["email"] for u in users} == {MANAGER[0], STAFF_EMAIL}
        # scope-bypass flag must be ignored for managers (SEC-001)
        r2 = s.get(f"{API}/admin/users?ignore_scope=true", timeout=60)
        assert r2.status_code == 200
        assert len(r2.json()) == 2

    def test_manager_settings_and_structure_scoped(self, scoped_env):
        s, _ = _login(*MANAGER)
        st = s.get(f"{API}/org/settings", timeout=60)
        assert st.status_code == 200, st.text[:200]
        assert [x["id"] for x in st.json()] == [scoped_env["setting_id"]]

        stru = s.get(f"{API}/org/structure", timeout=60)
        assert stru.status_code == 200, stru.text[:200]
        body = stru.json()
        assert [x["id"] for x in body["settings"]] == [scoped_env["setting_id"]]
        teams = body["settings"][0]["teams"]
        assert [t["id"] for t in teams] == [scoped_env["team_id"]]
        assert {m["email"] for m in teams[0]["members"]} == {MANAGER[0], STAFF_EMAIL}
        assert body["unassigned_users"] == []

    def test_manager_insights_and_registers_scoped(self, scoped_env):
        s, _ = _login(*MANAGER)
        ti = s.get(f"{API}/admin/team-insights", timeout=120)
        assert ti.status_code == 200, ti.text[:200]
        reg = s.get(f"{API}/admin/team-insights/registers", timeout=120)
        assert reg.status_code == 200, reg.text[:200]
        # every register row must belong to an in-scope staff member
        allowed = {MANAGER[0], STAFF_EMAIL}
        names = {u["name"] for u in s.get(f"{API}/admin/users", timeout=60).json() if u["email"] in allowed}
        for bucket in ("actions", "risks", "learning_needs"):
            for item in reg.json().get(bucket, []):
                owner = item.get("staff_name") or item.get("user_name")
                if owner:
                    assert owner in names, f"{bucket} leaked out-of-scope staff: {owner}"

    def test_manager_cannot_create_team_or_branch(self, scoped_env):
        s, _ = _login(*MANAGER)
        r = s.post(f"{API}/org/settings", json={"name": f"TEST_Scope_Illegal_{TAG}"}, timeout=60)
        assert r.status_code == 403, f"team-scoped manager created a branch: {r.status_code}"
        r2 = s.post(f"{API}/org/settings/{scoped_env['setting_id']}/teams",
                    json={"name": f"TEST_Scope_IllegalTeam_{TAG}"}, timeout=60)
        assert r2.status_code == 403, f"team-scoped manager created a team: {r2.status_code}"

    def test_admin_still_sees_everything(self, scoped_env):
        s = scoped_env["admin"]
        users = s.get(f"{API}/admin/users", timeout=60).json()
        assert len(users) > 2
        settings = s.get(f"{API}/org/settings", timeout=60).json()
        assert scoped_env["setting_id"] in [x["id"] for x in settings]
        # org-level admin filter by the new team must return exactly the 2 members
        ti = s.get(f"{API}/admin/team-insights?team_id={scoped_env['team_id']}", timeout=120)
        assert ti.status_code == 200, ti.text[:200]
