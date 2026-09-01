"""
Iteration 110 regression tests:
  1. POST /api/meetings/  date field_validator  -> garbage dates must 422 (not 200/500)
  2. init_db FK-supporting indexes present in Postgres
  3. Org settings/teams update round-trip (backend side of the stale-form race fix)
"""
import json
import os
import subprocess
import sys

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE_URL}/api"


# ── auth ──────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def cookies():
    out = subprocess.run(
        [sys.executable, "/app/backend/tests/get_tokens.py", "admin@supervision.com", "Admin123!"],
        capture_output=True, text=True, timeout=120, cwd="/app/backend",
    )
    line = [l for l in out.stdout.splitlines() if l.strip().startswith("{")]
    if not line:
        pytest.fail(f"login helper failed: {out.stdout[-500:]} {out.stderr[-500:]}")
    data = json.loads(line[-1])
    if data.get("me_status") != 200:
        pytest.fail(f"auth failed: {data}")
    return data["cookies"]


@pytest.fixture(scope="session")
def client(cookies):
    s = requests.Session()
    s.cookies.update(cookies)
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def created_meeting_ids():
    return []


@pytest.fixture(scope="session", autouse=True)
def cleanup(client, created_meeting_ids):
    yield
    for mid in created_meeting_ids:
        r = client.delete(f"{API}/meetings/{mid}")
        assert r.status_code in (200, 204, 404), f"cleanup failed for {mid}: {r.status_code}"


# ── 1. date validator ─────────────────────────────────────────────────────────
BAD_DATES = [
    "garbage",
    "",
    "not-a-date",
    "2026-13-45",
    "31/12/2026",
    "2026-02-30T10:00:00",
    "tomorrow",
    "0",
]


@pytest.mark.parametrize("bad", BAD_DATES)
def test_create_meeting_rejects_garbage_date(client, bad):
    r = client.post(f"{API}/meetings/", json={"title": "TEST_bad_date", "date": bad})
    assert r.status_code == 422, f"date={bad!r} -> {r.status_code} {r.text[:300]}"
    body = r.json()
    detail = json.dumps(body)
    assert "date" in detail.lower(), detail[:300]


def test_create_meeting_rejects_wrong_type_date(client):
    r = client.post(f"{API}/meetings/", json={"title": "TEST_bad_date", "date": {"a": 1}})
    assert r.status_code == 422, f"{r.status_code} {r.text[:300]}"


def test_create_meeting_rejects_missing_date(client):
    r = client.post(f"{API}/meetings/", json={"title": "TEST_no_date"})
    assert r.status_code == 422, f"{r.status_code} {r.text[:300]}"


GOOD_DATES = [
    "2026-08-15T10:30:00",
    "2026-08-15T10:30:00Z",
    "2026-08-15T10:30:00+01:00",
    "2026-08-15",
    "2026-08-15T10:30:00.123456",
]


@pytest.mark.parametrize("good", GOOD_DATES)
def test_create_meeting_accepts_valid_date(client, good, created_meeting_ids):
    r = client.post(f"{API}/meetings/", json={
        "title": "TEST_good_date", "date": good, "location": "TEST_loc", "meeting_type": "supervision",
    })
    assert r.status_code in (200, 201), f"date={good!r} -> {r.status_code} {r.text[:400]}"
    body = r.json()
    mid = body.get("id") or body.get("meeting_id")
    assert mid, body
    created_meeting_ids.append(mid)

    # persistence check
    g = client.get(f"{API}/meetings/{mid}")
    assert g.status_code == 200, g.text[:300]
    got = g.json()
    assert got["title"] == "TEST_good_date"
    assert got["date"], "date not persisted"


# ── 2. FK indexes ─────────────────────────────────────────────────────────────
EXPECTED_INDEXES = [
    "idx_analyses_org_id", "idx_meetings_setting_id", "idx_meetings_team_id",
    "idx_meetings_schedule_id", "idx_org_settings_manager_user_id",
    "idx_schedules_meeting_type_id", "idx_schedules_staff_user_id",
    "idx_teams_supervisor_user_id", "idx_transcripts_org_id",
    "idx_audio_files_org_id", "idx_audit_logs_org_id",
    "idx_evidence_feedback_org_id", "idx_evidence_feedback_meeting_id",
    "idx_invitations_org_id", "idx_meeting_prep_org_id",
    "idx_review_edits_org_id", "idx_reviewer_comments_org_id",
    "idx_standards_entries_org_id",
]


def test_fk_indexes_exist():
    sys.path.insert(0, "/app/backend")
    import asyncio
    for k, v in dotenv_values("/app/backend/.env").items():
        if v is not None:
            os.environ.setdefault(k, v)
    import database

    async def _run():
        pool = await database.create_pool()
        try:
            async with pool.acquire() as conn:
                rs = await conn.fetch("SELECT indexname FROM pg_indexes WHERE schemaname='public'")
            return {r["indexname"] for r in rs}
        finally:
            await database.close_pool()

    names = asyncio.run(_run())
    missing = [i for i in EXPECTED_INDEXES if i not in names]
    assert not missing, f"missing indexes: {missing}"


# ── 3. org settings/teams update round-trip ───────────────────────────────────
def test_setting_and_team_update_roundtrip(client):
    created_setting = None
    created_team = None
    try:
        r = client.post(f"{API}/org/settings", json={"name": "TEST_iter110_setting", "description": "d"})
        assert r.status_code in (200, 201), r.text[:300]
        created_setting = r.json()["id"]

        r = client.put(f"{API}/org/settings/{created_setting}", json={"name": "TEST_iter110_setting_v2", "description": "d2"})
        assert r.status_code == 200, r.text[:300]

        st = client.get(f"{API}/org/structure")
        assert st.status_code == 200
        s = next((x for x in st.json()["settings"] if x["id"] == created_setting), None)
        assert s and s["name"] == "TEST_iter110_setting_v2", s

        r = client.post(f"{API}/org/settings/{created_setting}/teams", json={"name": "TEST_iter110_team"})
        assert r.status_code in (200, 201), r.text[:300]
        created_team = r.json()["id"]

        r = client.put(f"{API}/org/teams/{created_team}", json={"name": "TEST_iter110_team_v2"})
        assert r.status_code == 200, r.text[:300]

        st = client.get(f"{API}/org/structure")
        s = next(x for x in st.json()["settings"] if x["id"] == created_setting)
        t = next((x for x in s.get("teams", []) if x["id"] == created_team), None)
        assert t and t["name"] == "TEST_iter110_team_v2", t
    finally:
        if created_team:
            client.delete(f"{API}/org/teams/{created_team}")
        if created_setting:
            client.delete(f"{API}/org/settings/{created_setting}")


# ── 4. BUG: empty-string UUID fields on team create/update (UI sends "") ──────
def test_team_create_with_empty_supervisor_string(client):
    """UI's inline 'Add Team' form posts supervisor_user_id: "" — must not 404."""
    r = client.post(f"{API}/org/settings", json={"name": "TEST_iter110_bug_setting", "description": ""})
    assert r.status_code in (200, 201), r.text[:200]
    sid = r.json()["id"]
    try:
        rt = client.post(f"{API}/org/settings/{sid}/teams",
                         json={"name": "TEST_iter110_bug_team", "description": "", "supervisor_user_id": ""})
        assert rt.status_code in (200, 201), (
            f"POST teams with supervisor_user_id='' -> {rt.status_code} {rt.text[:200]}"
        )
        tid = rt.json()["id"]
        # update with empty string too
        ru = client.put(f"{API}/org/teams/{tid}",
                        json={"name": "TEST_iter110_bug_team2", "description": "", "supervisor_user_id": ""})
        assert ru.status_code == 200, f"PUT team with supervisor_user_id='' -> {ru.status_code} {ru.text[:200]}"
        client.delete(f"{API}/org/teams/{tid}")
    finally:
        client.delete(f"{API}/org/settings/{sid}")


def test_setting_create_with_empty_manager_string(client):
    r = client.post(f"{API}/org/settings",
                    json={"name": "TEST_iter110_empty_mgr", "description": "", "manager_user_id": ""})
    assert r.status_code in (200, 201), r.text[:200]
    sid = r.json()["id"]
    ru = client.put(f"{API}/org/settings/{sid}",
                    json={"name": "TEST_iter110_empty_mgr2", "description": "", "manager_user_id": ""})
    assert ru.status_code == 200, f"{ru.status_code} {ru.text[:200]}"
    client.delete(f"{API}/org/settings/{sid}")
