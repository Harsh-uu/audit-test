"""Iteration 91 — Part 2 of the "Action Assignment Fix".

Covers:
  * unit: routers.processing._match_attendee_user_id (AI-name -> attendee user_id)
  * unit: routers.processing._get_rolled_actions strict assigned_to_user_id matching
          (+ legacy fuzzy-name fallback, + Part 1 manager-exclusion regression)
  * live API: PUT /api/review/{id}/actions and /learning_needs pass
          assigned_to_user_id through and persist (verified via GET /api/review/{id})

Run: cd /app/backend && python3 -m pytest tests/test_iter91_assignment.py -q
"""
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BE = dotenv_values("/app/backend/.env")
FE = dotenv_values("/app/frontend/.env")
BASE_URL = FE["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
DSN = BE["DATABASE_URL"]

ORG_ID = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"
MANAGER_EMAIL = "manager@supervision.com"
MANAGER_PW = "Manager123!"


# ---------------------------------------------------------------- helpers ----
def _att(uid, name, role):
    return {"user_id": uid, "name": name, "email": "", "role": role,
            "present": True, "reviewed": False, "reviewed_at": None}


async def _mfa_override(email):
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email)
    await conn.close()


@pytest.fixture(scope="module")
def mgr():
    """Authenticated manager session (MFA bypassed via DB override)."""
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": MANAGER_EMAIL, "password": MANAGER_PW}, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"manager login failed {r.status_code}: {r.text[:300]}")
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_mfa_override(MANAGER_EMAIL))
        r2 = s.post(f"{API}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=60)
        if r2.status_code != 200:
            pytest.fail(f"MFA verify failed {r2.status_code}: {r2.text[:300]}")
    me = s.get(f"{API}/auth/me", timeout=60)
    assert me.status_code == 200, me.text[:300]
    return s


@pytest.fixture(scope="module")
def target(mgr):
    """An in_review meeting with an analysis and >=2 attendees, plus its original state."""
    r = mgr.get(f"{API}/meetings/", timeout=60)
    assert r.status_code == 200, r.text[:300]
    meetings = r.json() if isinstance(r.json(), list) else r.json().get("meetings", [])
    for m in meetings:
        if m.get("status") in ("in_review", "reviewed") and len(m.get("attendees") or []) >= 2:
            det = mgr.get(f"{API}/review/{m['id']}", timeout=60)
            if det.status_code == 200 and det.json().get("analysis"):
                d = det.json()
                yield {
                    "id": m["id"],
                    "attendees": d["meeting"]["attendees"] if "meeting" in d else m["attendees"],
                    "orig_actions": d["analysis"].get("actions") or [],
                    "orig_lns": d["analysis"].get("learning_needs") or [],
                }
                # restore original state
                mgr.put(f"{API}/review/{m['id']}/actions",
                        json={"actions": d["analysis"].get("actions") or []}, timeout=60)
                mgr.put(f"{API}/review/{m['id']}/learning_needs",
                        json={"learning_needs": d["analysis"].get("learning_needs") or []}, timeout=60)
                return
    pytest.fail("No in_review/reviewed meeting with analysis + 2 attendees found")


# ------------------------------------------------- unit: name -> user_id ----
class TestMatchAttendeeUserId:
    def test_exact_and_case_insensitive(self):
        from utils.transcription_pipeline import _match_attendee_user_id
        atts = [_att("u1", "Demo User", "attendee"), _att("u2", "Demo Manager", "manager")]
        assert _match_attendee_user_id("Demo User", atts) == "u1"
        assert _match_attendee_user_id("  demo manager ", atts) == "u2"

    def test_no_match_and_empty(self):
        from utils.transcription_pipeline import _match_attendee_user_id
        atts = [_att("u1", "Demo User", "attendee")]
        assert _match_attendee_user_id("Someone Else", atts) is None
        assert _match_attendee_user_id("", atts) is None
        assert _match_attendee_user_id(None, atts) is None
        assert _match_attendee_user_id("Demo User", []) is None

    def test_attendee_without_user_id_is_skipped(self):
        from utils.transcription_pipeline import _match_attendee_user_id
        atts = [{"name": "Demo User", "role": "attendee"}]
        assert _match_attendee_user_id("Demo User", atts) is None


# ------------------------------------- unit: rolled actions strict matching --
@pytest.fixture(scope="class")
def rolled_env():
    """Insert a previous meeting whose analysis holds 4 differently-assigned actions.

    Uses synthetic user ids so no other row in the DB can interfere.
    """
    tag = uuid.uuid4().hex[:8]
    sup_a, sup_b, mgr_id = f"u-supA-{tag}", f"u-supB-{tag}", f"u-mgr-{tag}"
    prev_id, prev_analysis = f"test-i91-prev-{tag}", f"test-i91-an-{tag}"
    now = datetime.now(timezone.utc).isoformat()

    prev_attendees = [_att(mgr_id, "Iter91 Manager", "manager"),
                      _att(sup_a, "Iter91 SupA", "attendee"),
                      _att(sup_b, "Iter91 SupB", "attendee")]
    actions = [
        {"id": "a_linked_supA", "text": "linked to SupA", "completed": False,
         "assigned_to": "Iter91 SupA", "assigned_to_user_id": sup_a},
        {"id": "a_linked_supB", "text": "linked to SupB", "completed": False,
         "assigned_to": "Iter91 SupB", "assigned_to_user_id": sup_b},
        {"id": "a_linked_mgr", "text": "linked to manager", "completed": False,
         "assigned_to": "Iter91 Manager", "assigned_to_user_id": mgr_id},
        {"id": "a_legacy_name", "text": "legacy name only", "completed": False,
         "assigned_to": "Iter91 SupA"},
        {"id": "a_done", "text": "already complete", "completed": True,
         "assigned_to": "Iter91 SupA", "assigned_to_user_id": sup_a},
    ]

    async def setup():
        conn = await asyncpg.connect(DSN, ssl="require")
        await conn.execute(
            "INSERT INTO analyses (id, actions, risks, cqc_mappings, care_cert_mappings, "
            "custom_mappings, achievements, learning_needs, created_at) "
            "VALUES ($1,$2,'[]','[]','[]','[]','[]','[]',$3)",
            prev_analysis, json.dumps(actions), now)
        await conn.execute(
            "INSERT INTO meetings (id, org_id, title, date, meeting_type, created_by, created_by_name, "
            "sign_off_manager_id, attendees, status, analysis_id, recording_events, paused_periods, "
            "total_paused_duration_seconds, audio_deletion_status, created_at, updated_at) "
            "VALUES ($1,$2,'Iter91 Prev','2026-07-01','supervision',$3,'Iter91 Manager',"
            "NULL,$4,'in_review',$5,'[]','[]',0,'none',$6,$6)",
            prev_id, ORG_ID, mgr_id, json.dumps(prev_attendees), prev_analysis, now)
        await conn.close()

    asyncio.run(setup())
    yield {"conn_dsn": DSN, "tag": tag, "sup_a": sup_a, "sup_b": sup_b,
           "mgr_id": mgr_id, "prev_id": prev_id, "prev_analysis": prev_analysis}

    async def teardown():
        c = await asyncpg.connect(DSN, ssl="require")
        await c.execute("DELETE FROM meetings WHERE id=$1", prev_id)
        await c.execute("DELETE FROM analyses WHERE id=$1", prev_analysis)
        await c.close()
    asyncio.run(teardown())


def _roll(attendees, new_meeting_id, manager_id=None):
    from utils.transcription_pipeline import _get_rolled_actions

    async def run():
        c = await asyncpg.connect(DSN, ssl="require")
        try:
            return await _get_rolled_actions(c, attendees, new_meeting_id, manager_id=manager_id)
        finally:
            await c.close()
    return asyncio.run(run())


class TestRolledActionsStrictMatching:
    def test_only_actions_for_present_supervisee_roll_over(self, rolled_env):
        e = rolled_env
        new_atts = [_att(e["mgr_id"], "Iter91 Manager", "manager"),
                    _att(e["sup_a"], "Iter91 SupA", "attendee")]
        rolled = _roll(new_atts, f"test-i91-new-{e['tag']}")
        src = sorted(a["source_action_id"] for a in rolled)
        # SupA's linked action + the legacy name-only action (fuzzy fallback) must roll.
        # SupB's linked action, the manager's linked action, and the completed one must not.
        assert src == ["a_legacy_name", "a_linked_supA"], f"unexpected rolled set: {src}"
        for a in rolled:
            assert a["is_rolled_over"] is True and a["completed"] is False
            assert a["source_meeting_id"] == e["prev_id"]

    def test_manager_only_new_meeting_rolls_nothing(self, rolled_env):
        e = rolled_env
        rolled = _roll([_att(e["mgr_id"], "Iter91 Manager", "manager")],
                       f"test-i91-new2-{e['tag']}")
        assert rolled == [], f"manager-only meeting should not roll actions: {rolled}"

    def test_other_supervisee_does_not_inherit_linked_action(self, rolled_env):
        """Part-1 regression: shared manager must not link two supervisees' meetings."""
        e = rolled_env
        other = f"u-other-{e['tag']}"
        rolled = _roll([_att(e["mgr_id"], "Iter91 Manager", "manager"),
                        _att(other, "Iter91 Other", "attendee")],
                       f"test-i91-new3-{e['tag']}")
        assert rolled == [], f"unrelated supervisee inherited actions: {rolled}"

    def test_supB_gets_only_its_own_linked_action(self, rolled_env):
        e = rolled_env
        rolled = _roll([_att(e["mgr_id"], "Iter91 Manager", "manager"),
                        _att(e["sup_b"], "Iter91 SupB", "attendee")],
                       f"test-i91-new4-{e['tag']}")
        src = sorted(a["source_action_id"] for a in rolled)
        # a_legacy_name is assigned to "Iter91 SupA" (not an attendee here) -> excluded by fuzzy rule
        assert src == ["a_linked_supB"], f"unexpected rolled set: {src}"


# -------------------------------------------- live API: assignment passthrough
class TestAssignmentApiPassthrough:
    def test_action_with_assigned_user_id_persists(self, mgr, target):
        att = next((a for a in target["attendees"] if a.get("user_id")), None)
        assert att, "target meeting has no attendee with a user_id"
        new = {"id": f"action_manual_TEST_{uuid.uuid4().hex[:8]}", "text": "TEST_ assigned action",
               "assigned_to": att["name"], "assigned_to_user_id": att["user_id"],
               "due_date": "2026-09-01", "completed": False}
        payload = target["orig_actions"] + [new]
        r = mgr.put(f"{API}/review/{target['id']}/actions", json={"actions": payload}, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

        got = mgr.get(f"{API}/review/{target['id']}", timeout=60)
        assert got.status_code == 200
        saved = next((a for a in got.json()["analysis"]["actions"] if a["id"] == new["id"]), None)
        assert saved, "action not persisted"
        assert saved["assigned_to"] == att["name"]
        assert saved["assigned_to_user_id"] == att["user_id"]
        assert saved["due_date"] == "2026-09-01"

    def test_action_without_assignee_persists_as_null(self, mgr, target):
        new = {"id": f"action_manual_TEST_{uuid.uuid4().hex[:8]}", "text": "TEST_ unassigned action",
               "assigned_to": None, "assigned_to_user_id": None, "due_date": None, "completed": False}
        r = mgr.put(f"{API}/review/{target['id']}/actions",
                    json={"actions": target["orig_actions"] + [new]}, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        got = mgr.get(f"{API}/review/{target['id']}", timeout=60)
        saved = next((a for a in got.json()["analysis"]["actions"] if a["id"] == new["id"]), None)
        assert saved, "unassigned action not persisted"
        assert saved.get("assigned_to") is None
        assert saved.get("assigned_to_user_id") is None

    def test_learning_need_with_assigned_user_id_persists(self, mgr, target):
        att = next((a for a in target["attendees"] if a.get("user_id")), None)
        new = {"id": f"ln_manual_TEST_{uuid.uuid4().hex[:8]}", "text": "TEST_ assigned learning need",
               "assigned_to": att["name"], "assigned_to_user_id": att["user_id"],
               "due_date": None, "completed": False}
        r = mgr.put(f"{API}/review/{target['id']}/learning_needs",
                    json={"learning_needs": target["orig_lns"] + [new]}, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        got = mgr.get(f"{API}/review/{target['id']}", timeout=60)
        lns = got.json()["analysis"].get("learning_needs") or []
        saved = next((l for l in lns if l["id"] == new["id"]), None)
        assert saved, "learning need not persisted"
        assert saved["assigned_to"] == att["name"]
        assert saved["assigned_to_user_id"] == att["user_id"]

    def test_learning_need_without_assignee_persists(self, mgr, target):
        new = {"id": f"ln_manual_TEST_{uuid.uuid4().hex[:8]}", "text": "TEST_ unassigned learning need",
               "assigned_to": None, "assigned_to_user_id": None, "completed": False}
        r = mgr.put(f"{API}/review/{target['id']}/learning_needs",
                    json={"learning_needs": target["orig_lns"] + [new]}, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        got = mgr.get(f"{API}/review/{target['id']}", timeout=60)
        lns = got.json()["analysis"].get("learning_needs") or []
        saved = next((l for l in lns if l["id"] == new["id"]), None)
        assert saved and saved.get("assigned_to_user_id") is None

    def test_no_mongo_id_leak_in_review_payload(self, mgr, target):
        got = mgr.get(f"{API}/review/{target['id']}", timeout=60)
        assert '"_id"' not in json.dumps(got.json())
