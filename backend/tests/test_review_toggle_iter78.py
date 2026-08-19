"""Iteration 78 — Review tab toggle endpoints used by the EvidenceTab optimistic UI.

  PATCH /api/review/{meeting_id}/actions/{action_id}   (action complete toggle)
  PUT   /api/review/{meeting_id}/learning_needs        (learning need toggle)
Verifies persistence via a follow-up GET /api/review/{meeting_id}.
"""
import json
import os
import subprocess

import pytest
import requests
from dotenv import dotenv_values

fe = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or fe["REACT_APP_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"
MEETING_ID = "c20802af-17e3-4210-b497-13d09c9e67ec"
MANAGER = ("manager@supervision.com", "Manager123!")


@pytest.fixture(scope="module")
def client():
    """Manager session (MFA bypassed via helper) — only managers may toggle actions/learning needs."""
    out = subprocess.run(
        ["python3", "/app/backend/tests/get_tokens.py", MANAGER[0], MANAGER[1]],
        capture_output=True, text=True, timeout=180,
    )
    try:
        payload = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        pytest.fail(f"login helper failed: {out.stdout[-500:]} {out.stderr[-300:]}")
    if payload.get("error") or payload.get("me_status") != 200:
        pytest.fail(f"manager login failed: {payload}")
    s = requests.Session()
    for k, v in payload["cookies"].items():
        s.cookies.set(k, v)
    return s


def test_get_review_returns_analysis(client):
    r = client.get(f"{API}/review/{MEETING_ID}", timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    data = r.json()
    assert '"_id"' not in json.dumps(data)  # no raw mongo _id key
    analysis = data.get("analysis") or {}
    assert isinstance(analysis.get("actions", []), list)
    assert isinstance(analysis.get("learning_needs", []), list)


def _get_analysis(client):
    r = client.get(f"{API}/review/{MEETING_ID}", timeout=30)
    assert r.status_code == 200, r.text[:300]
    return r.json().get("analysis") or {}


def test_action_toggle_persists(client):
    analysis = _get_analysis(client)
    actions = analysis.get("actions") or []
    if not actions:
        pytest.skip("no actions on test meeting")
    action = actions[0]
    aid = action.get("id")
    assert aid, f"action missing id: {action}"
    target = not bool(action.get("completed"))

    r = client.patch(f"{API}/review/{MEETING_ID}/actions/{aid}", json={"completed": target}, timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    after = _get_analysis(client)
    match = [a for a in after.get("actions", []) if a.get("id") == aid]
    assert match, "action disappeared after toggle"
    assert bool(match[0].get("completed")) is target, f"not persisted: {match[0]}"
    if target:
        assert match[0].get("completed_at"), "completed_at not set"

    # restore
    r2 = client.patch(f"{API}/review/{MEETING_ID}/actions/{aid}", json={"completed": not target}, timeout=30)
    assert r2.status_code == 200


def test_action_toggle_unknown_id_returns_404(client):
    r = client.patch(f"{API}/review/{MEETING_ID}/actions/does_not_exist_iter78", json={"completed": True}, timeout=30)
    assert r.status_code in (400, 404), f"expected 4xx, got {r.status_code} {r.text[:300]}"


def test_learning_need_toggle_persists(client):
    analysis = _get_analysis(client)
    lns = list(analysis.get("learning_needs") or [])
    created = False
    if not lns:
        lns = [{"id": "ln_iter78", "text": "TEST_iter78 learning need", "assigned_to": None,
                "due_date": None, "completed": False}]
        r = client.put(f"{API}/review/{MEETING_ID}/learning_needs", json={"learning_needs": lns}, timeout=30)
        assert r.status_code == 200, f"seed failed {r.status_code} {r.text[:300]}"
        created = True
        lns = _get_analysis(client).get("learning_needs") or []
        assert lns, "seeded learning need not persisted"

    target = not bool(lns[0].get("completed"))
    updated = [dict(lns[0], completed=target)] + [dict(x) for x in lns[1:]]
    r = client.put(f"{API}/review/{MEETING_ID}/learning_needs", json={"learning_needs": updated}, timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    after = (_get_analysis(client).get("learning_needs") or [])
    assert after, "learning needs lost"
    assert bool(after[0].get("completed")) is target, f"not persisted: {after[0]}"

    # cleanup / restore
    if created:
        client.put(f"{API}/review/{MEETING_ID}/learning_needs", json={"learning_needs": []}, timeout=30)
    else:
        client.put(f"{API}/review/{MEETING_ID}/learning_needs", json={"learning_needs": lns}, timeout=30)


# ── smoke regression ────────────────────────────────────────────────────────
def test_smoke_core_endpoints(client):
    for path in ["/auth/me", "/meetings/", "/dashboard/stats"]:
        r = client.get(f"{API}{path}", timeout=30)
        assert r.status_code in (200, 404), f"{path} -> {r.status_code} {r.text[:200]}"
        if r.status_code == 404:
            print(f"NOTE: {path} returned 404 (endpoint may not exist)")
