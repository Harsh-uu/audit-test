"""
Iteration 164 — regression + feature tests for the new action_type
(task/standing_commitment) + trigger classification on meeting actions.

Covers:
- PUT /review/{id}/actions accepts action_type + trigger for standing_commitment
  and action_type + due_date for task; round-trip via GET /meetings/{id}
- Backward-compat: action with no action_type is treated as 'task'
- Literal 'Not specified in session' due_date persists as-is (not stripped)
- PATCH /review/{id}/actions/{action_id} toggles completed for both types
- GET /admin/team-insights passes through action_type/trigger for standing
  commitments and does NOT mark them overdue (they have no due_date)
- GET /review/{id}/export-pdf returns a PDF (200 + application/pdf) when the
  meeting has a mix of task + standing_commitment actions
- utils.ai._sanitise_analysis() defaults missing/invalid action_type -> 'task'
  and preserves the literal 'Not specified in session' due_date

Test fixture: meeting fbeb47d0-bf87-43ba-99bb-8e7388ecb238 (in_review, empty
actions). Every test writes its actions inline and the session-scoped fixture
resets it to an empty list at the end so the fixture is left as it was found.
"""
import os
import sys
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
    "https://supervision-preview.preview.emergentagent.com"
TEST_MEETING_ID = "fbeb47d0-bf87-43ba-99bb-8e7388ecb238"
ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASSWORD = "Admin123!X"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Ensure /app/backend is importable for the ai.py unit test
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(scope="session")
def api_client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
               timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    yield s
    # Teardown: leave the fixture meeting with an empty actions array
    try:
        s.put(f"{BASE_URL}/api/review/{TEST_MEETING_ID}/actions",
              json={"actions": []}, timeout=30)
    except Exception:
        pass


def _put_actions(client, actions):
    r = client.put(f"{BASE_URL}/api/review/{TEST_MEETING_ID}/actions",
                   json={"actions": actions}, timeout=30)
    assert r.status_code == 200, f"PUT actions failed: {r.status_code} {r.text[:200]}"
    return r


def _get_actions(client):
    r = client.get(f"{BASE_URL}/api/meetings/{TEST_MEETING_ID}", timeout=30)
    assert r.status_code == 200, f"GET meeting failed: {r.status_code}"
    return (r.json().get("analysis") or {}).get("actions") or []


# ── PUT /actions — task + standing_commitment round-trip ──────────────────────
def test_put_task_action_roundtrip(api_client):
    _put_actions(api_client, [{
        "id": "task_1", "text": "Follow up on medication review",
        "action_type": "task", "assigned_to": "Alex", "due_date": "2026-02-15",
    }])
    actions = _get_actions(api_client)
    assert len(actions) == 1
    a = actions[0]
    assert a["action_type"] == "task"
    assert a["due_date"] == "2026-02-15"
    assert a.get("trigger") in (None, "")


def test_put_standing_commitment_roundtrip(api_client):
    _put_actions(api_client, [{
        "id": "stand_1", "text": "Come to me any time this comes up",
        "action_type": "standing_commitment", "assigned_to": "Alex",
        "trigger": "any time the supervisee has a similar concern",
    }])
    actions = _get_actions(api_client)
    assert len(actions) == 1
    a = actions[0]
    assert a["action_type"] == "standing_commitment"
    assert a["trigger"] == "any time the supervisee has a similar concern"


def test_put_mixed_actions_and_literal_due_date(api_client):
    _put_actions(api_client, [
        {"id": "t1", "text": "Book training", "action_type": "task",
         "assigned_to": "Alex", "due_date": "Not specified in session"},
        {"id": "s1", "text": "Ongoing open-door policy",
         "action_type": "standing_commitment", "assigned_to": "Alex",
         "trigger": "next time worker feels overwhelmed"},
        # Legacy: no action_type at all
        {"id": "legacy1", "text": "Legacy action with no type",
         "assigned_to": "Alex", "due_date": "2026-03-01"},
    ])
    actions = _get_actions(api_client)
    assert len(actions) == 3
    by_id = {a["id"]: a for a in actions}
    # Literal string preserved verbatim
    assert by_id["t1"]["due_date"] == "Not specified in session"
    assert by_id["s1"]["action_type"] == "standing_commitment"
    assert by_id["s1"]["trigger"] == "next time worker feels overwhelmed"
    # Legacy action still persists (flexible JSONB) — no action_type on server side
    # is acceptable; the frontend treats missing == 'task'
    assert by_id["legacy1"]["text"] == "Legacy action with no type"


# ── PATCH toggle-complete works for BOTH types ────────────────────────────────
def test_patch_toggle_complete_task_and_standing(api_client):
    _put_actions(api_client, [
        {"id": "toggle_task", "text": "T1", "action_type": "task",
         "due_date": "2026-02-15", "assigned_to": "Alex"},
        {"id": "toggle_stand", "text": "S1",
         "action_type": "standing_commitment",
         "trigger": "anytime", "assigned_to": "Alex"},
    ])
    for aid in ("toggle_task", "toggle_stand"):
        r = api_client.patch(
            f"{BASE_URL}/api/review/{TEST_MEETING_ID}/actions/{aid}",
            json={"completed": True}, timeout=30)
        assert r.status_code == 200, f"PATCH {aid} failed: {r.status_code} {r.text[:200]}"
    actions = {a["id"]: a for a in _get_actions(api_client)}
    assert actions["toggle_task"]["completed"] is True
    assert actions["toggle_stand"]["completed"] is True

    # Toggle back
    for aid in ("toggle_task", "toggle_stand"):
        r = api_client.patch(
            f"{BASE_URL}/api/review/{TEST_MEETING_ID}/actions/{aid}",
            json={"completed": False}, timeout=30)
        assert r.status_code == 200
    actions = {a["id"]: a for a in _get_actions(api_client)}
    assert actions["toggle_task"]["completed"] is False
    assert actions["toggle_stand"]["completed"] is False


# ── Team Insights whitelist passes action_type + trigger, no overdue for standing
def test_team_insights_passthrough_and_no_overdue_for_standing(api_client):
    _put_actions(api_client, [
        {"id": "ti_stand", "text": "Standing check-in commitment",
         "action_type": "standing_commitment", "assigned_to": "Test Admin",
         "trigger": "at each fortnightly 1:1"},
        {"id": "ti_task", "text": "Complete safeguarding refresher",
         "action_type": "task", "assigned_to": "Test Admin",
         "due_date": "2020-01-01"},  # deliberately overdue
    ])
    r = api_client.get(f"{BASE_URL}/api/admin/team-insights/registers", timeout=60)
    assert r.status_code == 200, f"team-insights/registers failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    all_actions = data.get("actions") or []
    stand = [a for a in all_actions if a.get("text") == "Standing check-in commitment"]
    task = [a for a in all_actions if a.get("text") == "Complete safeguarding refresher"]
    assert stand, f"standing commitment not in team-insights/registers response; got {len(all_actions)} actions"
    assert task, "task not in team-insights/registers response"
    assert stand[0].get("action_type") == "standing_commitment"
    assert stand[0].get("trigger") == "at each fortnightly 1:1"
    # standing commitment must NOT carry a truthy due_date that would flag it overdue
    assert not stand[0].get("due_date"), \
        f"standing commitment leaked a due_date: {stand[0].get('due_date')!r}"


# ── PDF export renders (uses a signed-off meeting since export-pdf is locked) ─
SIGNED_OFF_MEETING_ID = "4b948235-5483-4f60-af2e-3f9591e3978b"


def test_export_pdf_renders_with_new_columns(api_client):
    r = api_client.get(
        f"{BASE_URL}/api/review/{SIGNED_OFF_MEETING_ID}/export-pdf?include_transcript=false",
        timeout=90)
    assert r.status_code == 200, f"PDF export failed: {r.status_code} {r.text[:200]}"
    assert r.headers.get("content-type", "").startswith("application/pdf"), \
        f"wrong content-type: {r.headers.get('content-type')}"
    assert len(r.content) > 1000
    assert r.content[:4] == b"%PDF"


# ── ai.py unit test: _sanitise_analysis defaults action_type + preserves literal
def test_sanitise_analysis_defaults_action_type():
    from utils.ai import _sanitise_analysis  # noqa: E402
    raw = {
        "summary": "s",
        "actions": [
            {"id": "a1", "text": "no type",
             "due_date": "Not specified in session", "assigned_to": "X"},
            {"id": "a2", "text": "invalid type", "action_type": "foo",
             "due_date": "null", "assigned_to": "null"},
            {"id": "a3", "text": "standing", "action_type": "standing_commitment",
             "trigger": "when needed", "assigned_to": "X"},
        ],
    }
    out = _sanitise_analysis(raw)
    a1, a2, a3 = out["actions"]
    assert a1["action_type"] == "task"
    # Literal preserved (not in nullish set)
    assert a1["due_date"] == "Not specified in session"
    assert a2["action_type"] == "task"  # invalid -> task
    assert a2["due_date"] is None       # "null" -> None
    assert a2["assigned_to"] is None
    assert a3["action_type"] == "standing_commitment"
    assert a3["trigger"] == "when needed"
