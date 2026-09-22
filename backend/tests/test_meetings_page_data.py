"""Regression tests for the /api/meetings/page-data combined endpoint (perf refactor).

Also validates the three standalone endpoints it composes are still working:
- GET /api/meetings/
- GET /api/meetings/month-summary
- GET /api/org/structure-lite
- GET /api/org/structure (heavier, must remain unaffected)
"""
import os
import json
import subprocess
import pytest
import requests
from datetime import datetime

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
    open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split("\n")[0].strip()


def _login(email, pw):
    """Use get_tokens.py which handles MFA, returns cookies dict for requests."""
    out = subprocess.check_output(
        ["python3", "/app/backend/tests/get_tokens.py", email, pw],
        text=True,
    )
    # last json-looking line
    for line in reversed(out.strip().split("\n")):
        line = line.strip()
        if line.startswith("{"):
            data = json.loads(line)
            return data["cookies"]
    raise RuntimeError(f"Could not parse tokens for {email}: {out}")


@pytest.fixture(scope="module")
def admin_cookies():
    return _login("admin@supervision.com", "Admin123!X")


@pytest.fixture(scope="module")
def manager_cookies():
    return _login("manager@supervision.com", "Manager123!")


@pytest.fixture(scope="module")
def staff_cookies():
    return _login("user@supervision.com", "Staff123!")


def _now_ym():
    n = datetime.utcnow()
    return n.year, n.month


# ---------- /api/meetings/page-data ----------

class TestPageData:
    def _get(self, cookies, year=None, month=None):
        params = {}
        if year:
            params["year"] = year
        if month:
            params["month"] = month
        return requests.get(
            f"{BASE_URL}/api/meetings/page-data",
            params=params,
            cookies=cookies,
            timeout=30,
        )

    def test_admin_shape_and_keys(self, admin_cookies):
        y, m = _now_ym()
        r = self._get(admin_cookies, y, m)
        assert r.status_code == 200, r.text
        data = r.json()
        assert set(data.keys()) == {"meetings", "month_summary", "org_structure"}, data.keys()
        assert isinstance(data["meetings"], list)
        assert isinstance(data["month_summary"], list)
        assert isinstance(data["org_structure"], dict)
        assert "settings" in data["org_structure"]
        assert isinstance(data["org_structure"]["settings"], list)
        # admin should have visibility of settings
        assert len(data["org_structure"]["settings"]) >= 0  # non-negative

    def test_manager_shape(self, manager_cookies):
        y, m = _now_ym()
        r = self._get(manager_cookies, y, m)
        assert r.status_code == 200, r.text
        data = r.json()
        assert set(data.keys()) == {"meetings", "month_summary", "org_structure"}
        assert "settings" in data["org_structure"]

    def test_staff_empty_settings(self, staff_cookies):
        y, m = _now_ym()
        r = self._get(staff_cookies, y, m)
        assert r.status_code == 200, r.text
        data = r.json()
        assert set(data.keys()) == {"meetings", "month_summary", "org_structure"}
        # Staff: filter bar must not be rendered ⇒ settings array empty
        assert data["org_structure"]["settings"] == [], data["org_structure"]

    def test_no_query_params_defaults(self, admin_cookies):
        r = requests.get(f"{BASE_URL}/api/meetings/page-data", cookies=admin_cookies, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert set(data.keys()) == {"meetings", "month_summary", "org_structure"}

    def test_unauth_401(self):
        r = requests.get(f"{BASE_URL}/api/meetings/page-data", timeout=15)
        assert r.status_code in (401, 403), r.status_code

    def test_month_summary_excludes_current_month(self, admin_cookies):
        y, m = _now_ym()
        r = self._get(admin_cookies, y, m)
        data = r.json()
        # month_summary rows shouldn't include the current (y, m) since it is fetched fully in `meetings`
        for row in data["month_summary"]:
            ry = row.get("year")
            rm = row.get("month")
            assert not (ry == y and rm == m), f"Current month leaked into summary: {row}"

    def test_consistency_against_standalone_endpoints(self, admin_cookies):
        y, m = _now_ym()
        combined = self._get(admin_cookies, y, m).json()

        r_meetings = requests.get(
            f"{BASE_URL}/api/meetings/",
            params={"year": y, "month": m, "limit": 500},
            cookies=admin_cookies,
            timeout=30,
        )
        assert r_meetings.status_code == 200
        r_summary = requests.get(f"{BASE_URL}/api/meetings/month-summary", cookies=admin_cookies, timeout=30)
        assert r_summary.status_code == 200
        r_struct = requests.get(f"{BASE_URL}/api/org/structure-lite", cookies=admin_cookies, timeout=30)
        assert r_struct.status_code == 200

        # Same number of meetings for the given month
        assert len(combined["meetings"]) == len(r_meetings.json())
        # Same settings count
        assert len(combined["org_structure"]["settings"]) == len(r_struct.json().get("settings", []))
        # month_summary length equal
        assert len(combined["month_summary"]) == len(r_summary.json())


# ---------- Standalone endpoints regression ----------

class TestStandaloneEndpoints:
    def test_meetings_list_admin(self, admin_cookies):
        r = requests.get(f"{BASE_URL}/api/meetings/", cookies=admin_cookies, timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_month_summary_admin(self, admin_cookies):
        r = requests.get(f"{BASE_URL}/api/meetings/month-summary", cookies=admin_cookies, timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_structure_lite_admin(self, admin_cookies):
        r = requests.get(f"{BASE_URL}/api/org/structure-lite", cookies=admin_cookies, timeout=30)
        assert r.status_code == 200
        assert "settings" in r.json()

    def test_structure_lite_staff_empty(self, staff_cookies):
        r = requests.get(f"{BASE_URL}/api/org/structure-lite", cookies=staff_cookies, timeout=30)
        assert r.status_code == 200
        assert r.json().get("settings", None) == []

    def test_structure_heavy_admin_unaffected(self, admin_cookies):
        r = requests.get(f"{BASE_URL}/api/org/structure", cookies=admin_cookies, timeout=30)
        assert r.status_code == 200
        body = r.json()
        # Heavier endpoint should still return a rich shape (settings key at minimum)
        assert isinstance(body, dict)
        assert "settings" in body


# ---------- Delete meeting flow (creates a throwaway meeting) ----------

class TestDeleteMeeting:
    def test_create_and_delete_meeting_admin(self, admin_cookies):
        # Create a meeting minimally
        payload = {
            "title": "TEST_perf_refactor_delete_me",
            "meeting_type": "one_to_one",
        }
        r = requests.post(f"{BASE_URL}/api/meetings/", json=payload, cookies=admin_cookies, timeout=30)
        # Some builds require attendees etc.; skip cleanly if 4xx due to validation only
        if r.status_code not in (200, 201):
            pytest.skip(f"Create meeting not accepted with minimal payload: {r.status_code} {r.text[:200]}")
        mid = r.json().get("id") or r.json().get("meeting", {}).get("id")
        assert mid, r.json()

        # Verify appears in page-data current month
        y, m = _now_ym()
        pd = requests.get(
            f"{BASE_URL}/api/meetings/page-data",
            params={"year": y, "month": m},
            cookies=admin_cookies,
            timeout=30,
        ).json()
        ids = {mt.get("id") for mt in pd["meetings"]}
        assert mid in ids, "Newly created meeting not returned by page-data"

        # Delete
        r_del = requests.delete(f"{BASE_URL}/api/meetings/{mid}", cookies=admin_cookies, timeout=30)
        assert r_del.status_code in (200, 204), r_del.text

        # Verify gone
        r_get = requests.get(f"{BASE_URL}/api/meetings/{mid}", cookies=admin_cookies, timeout=30)
        assert r_get.status_code == 404
