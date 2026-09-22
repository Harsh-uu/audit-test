"""Backend tests for AI Usage Report feature (m030) + orphan-teams filter fix.

Covers:
- GET /api/super-admin/ai-usage-report (auth, filters, stats math)
- GET /api/org/structure-lite (orphan team surfaced as 'unassigned' virtual setting)
- Direct DB update of an analyses row to simulate real data, then revert.
"""
import os
import json
import asyncio
import subprocess

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://supervision-preview.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ORPHAN_TEAM_ID = "1b9f4708-b3ae-4163-bfa1-4e1a8e668a99"
ADMIN_ORG_ID = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"


def _login(email, password):
    out = subprocess.check_output(
        ["python", "/app/backend/tests/get_tokens.py", email, password],
        cwd="/app/backend",
    ).decode()
    data = json.loads(out.strip().splitlines()[-1])
    return data["cookies"]


@pytest.fixture(scope="module")
def super_admin_cookies():
    return _login("superadmin@1two.one", "TestPass123!")


@pytest.fixture(scope="module")
def admin_cookies():
    return _login("admin@supervision.com", "Admin123!X")


# ---------- AI Usage Report: auth ----------
class TestAIUsageAuth:
    def test_unauthenticated_returns_401(self):
        r = requests.get(f"{API}/super-admin/ai-usage-report")
        assert r.status_code == 401

    def test_non_super_admin_returns_403(self, admin_cookies):
        r = requests.get(f"{API}/super-admin/ai-usage-report", cookies=admin_cookies)
        assert r.status_code == 403

    def test_super_admin_returns_200(self, super_admin_cookies):
        r = requests.get(f"{API}/super-admin/ai-usage-report", cookies=super_admin_cookies)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data and "stats" in data
        assert set(data["stats"].keys()) >= {"total", "fallback_count", "fallback_rate_pct", "avg_latency_ms", "by_provider"}


# ---------- AI Usage Report: empty state ----------
class TestAIUsageEmpty:
    def test_default_state_when_no_tracked_rows(self, super_admin_cookies):
        r = requests.get(f"{API}/super-admin/ai-usage-report", cookies=super_admin_cookies)
        assert r.status_code == 200
        data = r.json()
        # DB has zero tracked rows initially; verify shape works even for empty.
        assert isinstance(data["items"], list)
        assert isinstance(data["stats"]["total"], int)
        assert data["stats"]["fallback_rate_pct"] == 0 or isinstance(data["stats"]["fallback_rate_pct"], (int, float))


# ---------- AI Usage Report: filters + stats correctness (with seeded data) ----------
async def _run_db(sql, *args, fetch=False):
    import asyncpg
    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn)
    try:
        if fetch:
            rows = await conn.fetch(sql, *args)
            return [dict(r) for r in rows]
        else:
            return await conn.execute(sql, *args)
    finally:
        await conn.close()


class TestAIUsageWithSeededData:
    """Temporarily mark two analyses rows as AI-tracked, verify report,
    then revert."""

    @pytest.fixture(autouse=True, scope="class")
    def seed(self):
        # Load .env for DATABASE_URL
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        loop = asyncio.new_event_loop()
        rows = loop.run_until_complete(_run_db(
            "SELECT id FROM analyses ORDER BY created_at DESC LIMIT 2", fetch=True
        ))
        if len(rows) < 2:
            pytest.skip("Need at least 2 analyses rows in DB to seed test data")
        id1, id2 = rows[0]["id"], rows[1]["id"]
        loop.run_until_complete(_run_db(
            "UPDATE analyses SET ai_provider='gemini-2.5-flash', ai_fallback_used=FALSE, ai_latency_ms=4200, ai_fallback_reason=NULL WHERE id=$1",
            id1,
        ))
        loop.run_until_complete(_run_db(
            "UPDATE analyses SET ai_provider='o4-mini', ai_fallback_used=TRUE, ai_latency_ms=8500, ai_fallback_reason='Gemini quota exceeded (test)' WHERE id=$1",
            id2,
        ))
        yield {"id1": id1, "id2": id2}
        # Revert
        for aid in (id1, id2):
            loop.run_until_complete(_run_db(
                "UPDATE analyses SET ai_provider=NULL, ai_fallback_used=FALSE, ai_latency_ms=NULL, ai_fallback_reason=NULL WHERE id=$1",
                aid,
            ))
        loop.close()

    def test_report_returns_seeded_items(self, super_admin_cookies):
        r = requests.get(f"{API}/super-admin/ai-usage-report", cookies=super_admin_cookies)
        assert r.status_code == 200
        data = r.json()
        assert data["stats"]["total"] >= 2
        providers = data["stats"]["by_provider"]
        assert "gemini-2.5-flash" in providers
        assert "o4-mini" in providers
        # fallback_count should be >=1
        assert data["stats"]["fallback_count"] >= 1
        # fallback_rate_pct math
        expected_pct = round((data["stats"]["fallback_count"] / data["stats"]["total"]) * 100, 1)
        assert data["stats"]["fallback_rate_pct"] == expected_pct
        # avg_latency should be set
        assert data["stats"]["avg_latency_ms"] is not None
        # item shape
        item = data["items"][0]
        for key in ("meeting_id", "meeting_title", "org_name", "ai_provider", "ai_fallback_used", "ai_latency_ms", "analyzed_at"):
            assert key in item

    def test_provider_filter(self, super_admin_cookies):
        r = requests.get(f"{API}/super-admin/ai-usage-report",
                         cookies=super_admin_cookies,
                         params={"provider": "gemini-2.5-flash"})
        assert r.status_code == 200
        data = r.json()
        for item in data["items"]:
            assert item["ai_provider"] == "gemini-2.5-flash"

    def test_fallback_only_filter(self, super_admin_cookies):
        r = requests.get(f"{API}/super-admin/ai-usage-report",
                         cookies=super_admin_cookies,
                         params={"fallback_only": "true"})
        assert r.status_code == 200
        data = r.json()
        for item in data["items"]:
            assert item["ai_fallback_used"] is True


# ---------- Orphan teams filter fix ----------
class TestOrphanTeamsInStructureLite:
    def test_admin_sees_unassigned_setting_with_orphan_team(self, admin_cookies):
        r = requests.get(f"{API}/org/structure-lite", cookies=admin_cookies)
        assert r.status_code == 200
        data = r.json()
        settings = data.get("settings", [])
        unassigned = [s for s in settings if s["id"] == "unassigned"]
        assert len(unassigned) == 1, f"Expected one 'unassigned' virtual setting, got settings={[s['id'] for s in settings]}"
        assert unassigned[0]["name"] == "Unassigned (no setting)"
        team_ids = [t["id"] for t in unassigned[0]["teams"]]
        assert ORPHAN_TEAM_ID in team_ids, f"Expected orphan team {ORPHAN_TEAM_ID} in unassigned setting, got {team_ids}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
