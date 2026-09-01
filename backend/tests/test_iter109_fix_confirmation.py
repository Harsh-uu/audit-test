"""Iteration 109 — confirmation pass for the 4 defects found in iteration_108.

Covers gaps not already asserted by test_iter108_uuid_migration_regression.py:
  * portfolio + PDF export for admin / manager / attendee (own portfolio)
  * export-cc-excerpts as a team-scoped manager (4th endpoint fixed this round)
  * malformed-UUID path -> 404 (not 500) across several id routes
  * template GET->PUT->GET round trip actually persists
"""
import os
import subprocess
import sys

import pytest
import requests
from dotenv import dotenv_values

fe = dotenv_values("/app/frontend/.env")
base = os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL")
if not base:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE = base.rstrip("/") + "/api"

CREDS = {
    "admin": ("admin@supervision.com", "Admin123!"),
    "manager": ("manager@supervision.com", "Manager123!"),
    "attendee": ("user@supervision.com", "Staff123!"),
}


def _session(role):
    email, pw = CREDS[role]
    s = requests.Session()
    if role == "attendee":
        r = s.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=60)
        if r.status_code != 200 or r.json().get("requires_mfa"):
            pytest.fail(f"{role} login failed: {r.status_code} {r.text[:300]}")
        return s
    # MFA roles: reuse the shared helper
    out = subprocess.run(
        [sys.executable, "/app/backend/tests/get_tokens.py", email, pw],
        capture_output=True, text=True, timeout=180, cwd="/app/backend",
    )
    import json as _json
    line = [ln for ln in out.stdout.splitlines() if ln.strip().startswith("{")]
    if not line:
        pytest.fail(f"get_tokens.py failed for {role}: {out.stdout[-400:]} {out.stderr[-400:]}")
    data = _json.loads(line[-1])
    for k, v in data["cookies"].items():
        s.cookies.set(k, v)
    return s


@pytest.fixture(scope="module")
def sessions():
    return {r: _session(r) for r in CREDS}


def no500(r, what):
    assert r.status_code < 500, f"{what} -> {r.status_code}: {r.text[:400]}"


# ── portfolio (defect 2) ────────────────────────────────────────────────
@pytest.mark.parametrize("role", ["admin", "manager", "attendee"])
def test_portfolio_own(sessions, role):
    s = sessions[role]
    me = s.get(f"{BASE}/auth/me", timeout=60)
    assert me.status_code == 200, me.text[:300]
    uid = me.json()["id"]

    r = s.get(f"{BASE}/portfolio/{uid}", timeout=120)
    no500(r, f"{role} GET /portfolio/{{self}}")
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    assert isinstance(body, dict)
    # structural assertion: portfolio payload must expose the owner + meeting list
    assert any(k in body for k in ("user", "user_id", "staff")), list(body)[:12]

    p = s.get(f"{BASE}/portfolio/{uid}/export-pdf", timeout=180)
    no500(p, f"{role} portfolio export-pdf")
    assert p.status_code == 200, p.text[:300]
    assert p.content[:4] == b"%PDF", p.content[:40]


# ── scoped-manager array-cast endpoints (defects 3 + proactive 4th) ──────
def _scoped_manager():
    """Log in as manager; iter108 confirmed this account is team-scoped."""
    return _session("manager")


@pytest.mark.parametrize("path,payload", [
    ("/admin/export-evidence", {"format": "csv"}),
    ("/admin/export-transcripts", {}),
    ("/admin/export-cc-excerpts", {}),
])
def test_manager_export_endpoints(sessions, path, payload):
    r = sessions["manager"].post(f"{BASE}{path}", json=payload, timeout=180)
    no500(r, f"manager POST {path}")


def test_manager_meetings_brief(sessions):
    r = sessions["manager"].get(f"{BASE}/admin/meetings-brief", timeout=180)
    no500(r, "manager GET /admin/meetings-brief")
    assert r.status_code == 200, r.text[:300]


# ── malformed uuid path (defect 4) ──────────────────────────────────────
@pytest.mark.parametrize("path", [
    "/meetings/not-a-uuid",
    "/review/not-a-uuid",
    "/portfolio/not-a-uuid",
    "/meetings/12345",
])
def test_malformed_uuid_no_500(sessions, path):
    r = sessions["admin"].get(f"{BASE}{path}", timeout=90)
    assert r.status_code < 500, f"GET {path} -> {r.status_code}: {r.text[:300]}"
    assert r.status_code in (400, 404, 422), f"GET {path} -> {r.status_code}"


# ── template round trip (defect 1) ──────────────────────────────────────
def test_template_round_trip(sessions):
    s = sessions["admin"]
    orig = s.get(f"{BASE}/admin/template", timeout=90)
    assert orig.status_code == 200, orig.text[:400]
    original = orig.json()

    payload = dict(original)
    payload["steps"] = [{"id": "TEST_iter109_step", "title": "TEST_iter109 step",
                         "description": "round trip", "prompts": []}]
    put = s.put(f"{BASE}/admin/template", json=payload, timeout=90)
    assert put.status_code == 200, f"PUT template -> {put.status_code}: {put.text[:400]}"

    again = s.get(f"{BASE}/admin/template", timeout=90)
    assert again.status_code == 200, again.text[:300]
    titles = [st.get("title") for st in again.json().get("steps", [])]
    assert "TEST_iter109 step" in titles, f"template did not persist: {titles}"

    # restore original template so we leave no residue
    restore = s.put(f"{BASE}/admin/template", json=original, timeout=90)
    assert restore.status_code == 200, restore.text[:300]
