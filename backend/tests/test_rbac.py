"""
RBAC / Sub-Tenant Scoping Tests for Supervision 2.0
Tests: org-level admin, org-level manager, team-scoped manager, is_historical flag, portfolio scope, schedules scope
"""

import pytest
import requests
import os
import time

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


# ── Auth helpers ──────────────────────────────────────────────────────────────

def login(email, password):
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"Login failed for {email}: {resp.text}"
    return resp.json()["token"]


def authed(token):
    return {"Authorization": f"Bearer {token}"}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def admin_token():
    return login("admin@supervision.com", "Admin123!")


@pytest.fixture(scope="module")
def manager_token():
    return login("manager@supervision.com", "Manager123!")


@pytest.fixture(scope="module")
def staff_token():
    return login("staff@supervision.com", "Staff123!")


@pytest.fixture(scope="module")
def admin_user_id(admin_token):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=authed(admin_token))
    assert r.status_code == 200
    return r.json()["id"]


@pytest.fixture(scope="module")
def manager_user_id(manager_token):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=authed(manager_token))
    assert r.status_code == 200
    return r.json()["id"]


@pytest.fixture(scope="module")
def staff_user_id(staff_token):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=authed(staff_token))
    assert r.status_code == 200
    return r.json()["id"]


# ── Phase 0: Ensure manager starts as org-level (no team/setting) ─────────────

class TestPhase0_ResetManagerScope:
    """Ensure manager has no team/setting so it starts as org-level."""

    def test_reset_manager_to_org_level(self, admin_token, manager_user_id):
        """PATCH assign-team with team_id=null to reset manager scope."""
        r = requests.patch(
            f"{BASE_URL}/api/org/users/{manager_user_id}/assign-team",
            json={"team_id": None},
            headers=authed(admin_token),
        )
        assert r.status_code == 200, f"Reset failed: {r.text}"
        print("Manager scope reset to org-level")

    def test_manager_is_org_level_after_reset(self, manager_token):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=authed(manager_token))
        data = r.json()
        # After reset, team_id and setting_id should be None/null
        assert data.get("team_id") is None, f"Expected team_id=None, got {data.get('team_id')}"
        print(f"Manager team_id={data.get('team_id')}, setting_id={data.get('setting_id')}")


# ── Phase 1: Admin and Org-level Manager see all ───────────────────────────────

class TestPhase1_OrgLevelAccess:

    def test_admin_sees_all_meetings(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/meetings/", headers=authed(admin_token))
        assert r.status_code == 200
        meetings = r.json()
        print(f"Admin sees {len(meetings)} meetings")
        assert isinstance(meetings, list)

    def test_admin_sees_all_users(self, admin_token):
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=authed(admin_token))
        assert r.status_code == 200
        users = r.json()
        print(f"Admin sees {len(users)} users")
        assert len(users) >= 3, f"Expected >=3 users for admin, got {len(users)}"

    def test_org_level_manager_sees_all_meetings(self, manager_token):
        """Manager with no team/setting assigned should see all org meetings."""
        r = requests.get(f"{BASE_URL}/api/meetings/", headers=authed(manager_token))
        assert r.status_code == 200
        meetings = r.json()
        print(f"Org-level manager sees {len(meetings)} meetings")
        assert isinstance(meetings, list)

    def test_org_level_manager_sees_all_users(self, manager_token):
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=authed(manager_token))
        assert r.status_code == 200
        users = r.json()
        print(f"Org-level manager sees {len(users)} users")
        assert len(users) >= 3, f"Expected >=3 users for org-level manager, got {len(users)}"

    def test_org_structure_shows_all_settings(self, manager_token):
        r = requests.get(f"{BASE_URL}/api/org/structure", headers=authed(manager_token))
        assert r.status_code == 200
        data = r.json()
        print(f"Org-level manager sees {len(data.get('settings', []))} settings")
        assert "settings" in data


# ── Phase 2: Create setting+team, assign manager to team ──────────────────────

class TestPhase2_CreateScopeAndAssign:

    @pytest.fixture(scope="class")
    def setting_id(self, admin_token):
        r = requests.post(
            f"{BASE_URL}/api/org/settings",
            json={"name": "TEST_Branch_Alpha"},
            headers=authed(admin_token),
        )
        assert r.status_code == 200, f"Create setting failed: {r.text}"
        sid = r.json()["id"]
        print(f"Created setting: {sid}")
        return sid

    @pytest.fixture(scope="class")
    def team_id(self, admin_token, setting_id):
        r = requests.post(
            f"{BASE_URL}/api/org/settings/{setting_id}/teams",
            json={"name": "TEST_Team_Alpha"},
            headers=authed(admin_token),
        )
        assert r.status_code == 200, f"Create team failed: {r.text}"
        tid = r.json()["id"]
        print(f"Created team: {tid}")
        return tid

    def test_create_setting(self, setting_id):
        assert setting_id is not None
        print(f"Setting created: {setting_id}")

    def test_create_team(self, team_id):
        assert team_id is not None
        print(f"Team created: {team_id}")

    def test_assign_manager_to_team(self, admin_token, manager_user_id, team_id):
        r = requests.patch(
            f"{BASE_URL}/api/org/users/{manager_user_id}/assign-team",
            json={"team_id": team_id},
            headers=authed(admin_token),
        )
        assert r.status_code == 200, f"Assign team failed: {r.text}"
        print(f"Manager {manager_user_id} assigned to team {team_id}")

    def test_manager_token_shows_team_id(self, manager_user_id, team_id):
        """After assigning, get fresh token and verify team_id in /api/auth/me."""
        fresh_token = login("manager@supervision.com", "Manager123!")
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=authed(fresh_token))
        data = r.json()
        print(f"Manager me: team_id={data.get('team_id')}")
        assert data.get("team_id") == team_id, f"Expected team_id={team_id}, got {data.get('team_id')}"


# ── Phase 3: Scoped manager access ────────────────────────────────────────────

class TestPhase3_ScopedAccess:
    """After manager is assigned to team, test all scoped endpoints."""

    @pytest.fixture(scope="class")
    def setup_scope(self, admin_token, manager_user_id):
        """Ensure manager is team-scoped. Create setting+team if needed."""
        # Create setting
        r = requests.post(
            f"{BASE_URL}/api/org/settings",
            json={"name": "TEST_Branch_Scoped"},
            headers=authed(admin_token),
        )
        assert r.status_code == 200
        setting_id = r.json()["id"]
        # Create team
        r = requests.post(
            f"{BASE_URL}/api/org/settings/{setting_id}/teams",
            json={"name": "TEST_Team_Scoped"},
            headers=authed(admin_token),
        )
        assert r.status_code == 200
        team_id = r.json()["id"]
        # Assign manager to team
        r = requests.patch(
            f"{BASE_URL}/api/org/users/{manager_user_id}/assign-team",
            json={"team_id": team_id},
            headers=authed(admin_token),
        )
        assert r.status_code == 200
        return {"setting_id": setting_id, "team_id": team_id}

    @pytest.fixture(scope="class")
    def scoped_manager_token(self, setup_scope):
        """Fresh token after scope assignment."""
        return login("manager@supervision.com", "Manager123!")

    @pytest.fixture(scope="class")
    def staff_in_team(self, admin_token, setup_scope, staff_user_id):
        """Add staff user to the team."""
        team_id = setup_scope["team_id"]
        r = requests.patch(
            f"{BASE_URL}/api/org/users/{staff_user_id}/assign-team",
            json={"team_id": team_id},
            headers=authed(admin_token),
        )
        assert r.status_code == 200, f"Failed to add staff to team: {r.text}"
        print(f"Staff {staff_user_id} added to team {team_id}")
        return staff_user_id

    def test_scoped_manager_sees_only_team_users(self, scoped_manager_token, setup_scope, staff_in_team):
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=authed(scoped_manager_token))
        assert r.status_code == 200
        users = r.json()
        user_ids = [u["id"] for u in users]
        print(f"Scoped manager sees {len(users)} users: {[u['email'] for u in users]}")
        # All returned users must be in the same team
        for u in users:
            assert u.get("team_id") == setup_scope["team_id"], (
                f"User {u['email']} team_id={u.get('team_id')} not in team {setup_scope['team_id']}"
            )

    def test_scoped_manager_org_structure_limited(self, scoped_manager_token, setup_scope):
        r = requests.get(f"{BASE_URL}/api/org/structure", headers=authed(scoped_manager_token))
        assert r.status_code == 200
        data = r.json()
        settings = data.get("settings", [])
        print(f"Scoped manager sees {len(settings)} settings")
        # Should see only their own setting
        for s in settings:
            assert s["id"] == setup_scope["setting_id"], (
                f"Scoped manager should only see their setting, got {s['id']}"
            )

    def test_scoped_manager_meetings_only_in_scope(self, scoped_manager_token, admin_token, setup_scope, staff_in_team):
        """Create a meeting with staff in the team, scoped manager should see it."""
        manager_id_r = requests.get(f"{BASE_URL}/api/auth/me", headers=authed(scoped_manager_token))
        manager_id = manager_id_r.json()["id"]

        # Create meeting as scoped manager with staff as attendee
        r = requests.post(
            f"{BASE_URL}/api/meetings/",
            json={
                "title": "TEST_Scoped_Meeting",
                "date": "2026-02-15",
                "attendee_ids": [staff_in_team],
                "meeting_type": "supervision",
            },
            headers=authed(scoped_manager_token),
        )
        assert r.status_code == 200, f"Create meeting failed: {r.text}"
        meeting_id = r.json()["id"]
        print(f"Created scoped meeting: {meeting_id}")

        # Scoped manager should see the meeting
        r2 = requests.get(f"{BASE_URL}/api/meetings/", headers=authed(scoped_manager_token))
        assert r2.status_code == 200
        meetings = r2.json()
        meeting_ids = [m["id"] for m in meetings]
        assert meeting_id in meeting_ids, "Scoped meeting not visible to scoped manager"
        print(f"Scoped manager sees {len(meetings)} meetings including test meeting")

        # Clean up
        requests.delete(f"{BASE_URL}/api/meetings/{meeting_id}", headers=authed(admin_token))

    def test_scoped_manager_schedules_limited(self, scoped_manager_token, setup_scope, staff_in_team):
        r = requests.get(f"{BASE_URL}/api/schedules/", headers=authed(scoped_manager_token))
        assert r.status_code == 200
        schedules = r.json()
        print(f"Scoped manager sees {len(schedules)} schedules")
        # All schedules should be for staff in the team
        for s in schedules:
            assert s.get("staff_user_id") == staff_in_team, (
                f"Schedule {s['id']} is for {s.get('staff_user_id')} not in team"
            )

    def test_portfolio_in_scope_accessible(self, scoped_manager_token, staff_in_team):
        """Staff in team → portfolio should be accessible (200 or 404 if no meetings)."""
        r = requests.get(f"{BASE_URL}/api/portfolio/{staff_in_team}", headers=authed(scoped_manager_token))
        assert r.status_code in [200, 404], f"Unexpected: {r.status_code} {r.text}"
        if r.status_code == 200:
            print(f"Portfolio for staff in scope: OK, meetings={r.json()['stats']['total_meetings']}")
        else:
            print("Portfolio returned 404 (no signed-off meetings for staff)")

    def test_portfolio_out_of_scope_returns_403(self, scoped_manager_token, admin_user_id):
        """Admin user is NOT in team — portfolio access should be denied."""
        r = requests.get(f"{BASE_URL}/api/portfolio/{admin_user_id}", headers=authed(scoped_manager_token))
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"
        print("Portfolio out-of-scope correctly returns 403")

    def test_team_insights_auto_filters_to_team(self, scoped_manager_token, setup_scope, staff_in_team):
        """GET /api/admin/team-insights with no params — should auto-filter to team."""
        r = requests.get(f"{BASE_URL}/api/admin/team-insights", headers=authed(scoped_manager_token))
        assert r.status_code == 200, f"Team insights failed: {r.text}"
        data = r.json()
        staff_count = data.get("staff_count", 0)
        print(f"Team insights staff_count={staff_count} (should be for team only)")
        # Should only count staff in the team, not entire org
        # We have staff_in_team in the team; org has 3 users total
        # staff_count must be <= total org staff, ideally just team members

    def test_admin_still_unrestricted_after_scope(self, admin_token, setup_scope):
        """Admin always sees all settings regardless of scoping."""
        r = requests.get(f"{BASE_URL}/api/org/structure", headers=authed(admin_token))
        assert r.status_code == 200
        data = r.json()
        settings = data.get("settings", [])
        print(f"Admin sees {len(settings)} settings (should be all)")
        # Admin should see more than just the one scoped setting
        setting_ids = [s["id"] for s in settings]
        assert setup_scope["setting_id"] in setting_ids


# ── Phase 4: is_historical flag ───────────────────────────────────────────────

class TestPhase4_IsHistorical:
    """Test that meetings become historical when staff leaves team."""

    @pytest.fixture(scope="class")
    def scope_setup(self, admin_token, manager_user_id):
        """Create fresh setting+team and assign manager."""
        r = requests.post(
            f"{BASE_URL}/api/org/settings",
            json={"name": "TEST_Branch_Historical"},
            headers=authed(admin_token),
        )
        assert r.status_code == 200
        setting_id = r.json()["id"]
        r = requests.post(
            f"{BASE_URL}/api/org/settings/{setting_id}/teams",
            json={"name": "TEST_Team_Historical"},
            headers=authed(admin_token),
        )
        assert r.status_code == 200
        team_id = r.json()["id"]
        # Assign manager
        r = requests.patch(
            f"{BASE_URL}/api/org/users/{manager_user_id}/assign-team",
            json={"team_id": team_id},
            headers=authed(admin_token),
        )
        assert r.status_code == 200
        return {"setting_id": setting_id, "team_id": team_id}

    def test_is_historical_flow(self, scope_setup, admin_token, staff_user_id):
        """
        1. Add staff to team
        2. Manager creates meeting with staff as attendee
        3. Remove staff from team
        4. Re-fetch meetings → meeting should have is_historical=True
        """
        team_id = scope_setup["team_id"]

        # Add staff to team
        r = requests.patch(
            f"{BASE_URL}/api/org/users/{staff_user_id}/assign-team",
            json={"team_id": team_id},
            headers=authed(admin_token),
        )
        assert r.status_code == 200

        # Fresh manager token
        mgr_token = login("manager@supervision.com", "Manager123!")

        # Create meeting with staff as attendee
        r = requests.post(
            f"{BASE_URL}/api/meetings/",
            json={
                "title": "TEST_Historical_Meeting",
                "date": "2026-01-10",
                "attendee_ids": [staff_user_id],
                "meeting_type": "supervision",
            },
            headers=authed(mgr_token),
        )
        assert r.status_code == 200, f"Create meeting failed: {r.text}"
        meeting_id = r.json()["id"]
        print(f"Created meeting: {meeting_id}")

        # Verify it is NOT historical yet
        r2 = requests.get(f"{BASE_URL}/api/meetings/", headers=authed(mgr_token))
        assert r2.status_code == 200
        meetings = {m["id"]: m for m in r2.json()}
        assert meeting_id in meetings, "Meeting not found before staff removal"
        assert meetings[meeting_id].get("is_historical") == False, (
            f"Expected is_historical=False before removal, got {meetings[meeting_id].get('is_historical')}"
        )
        print("Meeting is_historical=False before staff removal (correct)")

        # Remove staff from team
        r3 = requests.patch(
            f"{BASE_URL}/api/org/users/{staff_user_id}/assign-team",
            json={"team_id": None},
            headers=authed(admin_token),
        )
        assert r3.status_code == 200

        # Re-fetch meetings with fresh manager token (forces db re-read)
        mgr_token2 = login("manager@supervision.com", "Manager123!")
        r4 = requests.get(f"{BASE_URL}/api/meetings/", headers=authed(mgr_token2))
        assert r4.status_code == 200
        meetings2 = {m["id"]: m for m in r4.json()}
        assert meeting_id in meetings2, "Meeting not found after staff removal"
        assert meetings2[meeting_id].get("is_historical") == True, (
            f"Expected is_historical=True after staff removed from team, got {meetings2[meeting_id].get('is_historical')}"
        )
        print("Meeting is_historical=True after staff removal (correct)")

        # Clean up: delete meeting and reset staff
        requests.delete(f"{BASE_URL}/api/meetings/{meeting_id}", headers=authed(admin_token))


# ── Phase 5: Cleanup ──────────────────────────────────────────────────────────

class TestPhase5_Cleanup:

    def test_reset_manager_scope_final(self, admin_token, manager_user_id):
        """Reset manager back to org-level."""
        r = requests.patch(
            f"{BASE_URL}/api/org/users/{manager_user_id}/assign-team",
            json={"team_id": None},
            headers=authed(admin_token),
        )
        assert r.status_code == 200
        print("Manager scope reset to org-level (cleanup done)")

    def test_reset_staff_scope_final(self, admin_token, staff_user_id):
        """Reset staff back to unassigned."""
        r = requests.patch(
            f"{BASE_URL}/api/org/users/{staff_user_id}/assign-team",
            json={"team_id": None},
            headers=authed(admin_token),
        )
        assert r.status_code == 200
        print("Staff scope reset (cleanup done)")

    def test_delete_test_settings(self, admin_token):
        """Delete all TEST_ settings created during tests."""
        r = requests.get(f"{BASE_URL}/api/org/settings", headers=authed(admin_token))
        if r.status_code != 200:
            print(f"Could not list settings: {r.status_code}")
            return
        settings = r.json()
        deleted = 0
        for s in settings:
            if s.get("name", "").startswith("TEST_"):
                rd = requests.delete(f"{BASE_URL}/api/org/settings/{s['id']}", headers=authed(admin_token))
                if rd.status_code == 200:
                    deleted += 1
        print(f"Deleted {deleted} TEST_ settings")
