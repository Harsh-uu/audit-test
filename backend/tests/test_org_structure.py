"""Tests for Organisation Structure API - /api/org/* endpoints"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


@pytest.fixture(scope="module")
def auth_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@supervision.com", "password": "Admin123!"
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json().get("access_token") or resp.cookies.get("access_token")


@pytest.fixture(scope="module")
def headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def session(headers):
    s = requests.Session()
    s.headers.update(headers)
    return s


class TestOrgStructure:
    """Test org structure read endpoints"""

    def test_get_structure(self, session):
        resp = session.get(f"{BASE_URL}/api/org/structure")
        assert resp.status_code == 200
        data = resp.json()
        assert "settings" in data
        assert "unassigned_users" in data
        assert isinstance(data["settings"], list)
        assert isinstance(data["unassigned_users"], list)

    def test_get_settings(self, session):
        resp = session.get(f"{BASE_URL}/api/org/settings")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestSettingsCRUD:
    """Test settings CRUD"""
    created_setting_id = None

    def test_create_setting(self, session):
        resp = session.post(f"{BASE_URL}/api/org/settings", json={
            "name": "TEST_Setting_Alpha", "description": "Test setting"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "TEST_Setting_Alpha"
        assert "id" in data
        TestSettingsCRUD.created_setting_id = data["id"]

    def test_setting_appears_in_structure(self, session):
        resp = session.get(f"{BASE_URL}/api/org/structure")
        assert resp.status_code == 200
        settings = resp.json()["settings"]
        names = [s["name"] for s in settings]
        assert "TEST_Setting_Alpha" in names

    def test_update_setting(self, session):
        sid = TestSettingsCRUD.created_setting_id
        assert sid, "No setting created"
        resp = session.put(f"{BASE_URL}/api/org/settings/{sid}", json={
            "name": "TEST_Setting_Alpha_Updated", "description": "Updated"
        })
        assert resp.status_code == 200

    def test_verify_setting_update_persisted(self, session):
        resp = session.get(f"{BASE_URL}/api/org/structure")
        settings = resp.json()["settings"]
        names = [s["name"] for s in settings]
        assert "TEST_Setting_Alpha_Updated" in names

    def test_delete_setting(self, session):
        sid = TestSettingsCRUD.created_setting_id
        assert sid
        resp = session.delete(f"{BASE_URL}/api/org/settings/{sid}")
        assert resp.status_code == 200

    def test_setting_removed_after_delete(self, session):
        resp = session.get(f"{BASE_URL}/api/org/structure")
        settings = resp.json()["settings"]
        ids = [s["id"] for s in settings]
        assert TestSettingsCRUD.created_setting_id not in ids


class TestTeamsCRUD:
    """Test teams CRUD within a setting"""
    setting_id = None
    team_id = None

    def test_setup_create_setting(self, session):
        resp = session.post(f"{BASE_URL}/api/org/settings", json={
            "name": "TEST_Setting_ForTeams"
        })
        assert resp.status_code == 200
        TestTeamsCRUD.setting_id = resp.json()["id"]

    def test_create_team(self, session):
        sid = TestTeamsCRUD.setting_id
        resp = session.post(f"{BASE_URL}/api/org/settings/{sid}/teams", json={
            "name": "TEST_Team_Beta", "description": "A test team"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "TEST_Team_Beta"
        assert "id" in data
        TestTeamsCRUD.team_id = data["id"]

    def test_team_appears_in_structure(self, session):
        resp = session.get(f"{BASE_URL}/api/org/structure")
        settings = resp.json()["settings"]
        setting = next((s for s in settings if s["id"] == TestTeamsCRUD.setting_id), None)
        assert setting is not None
        team_names = [t["name"] for t in setting.get("teams", [])]
        assert "TEST_Team_Beta" in team_names

    def test_update_team(self, session):
        tid = TestTeamsCRUD.team_id
        resp = session.put(f"{BASE_URL}/api/org/teams/{tid}", json={
            "name": "TEST_Team_Beta_Updated"
        })
        assert resp.status_code == 200

    def test_delete_team(self, session):
        resp = session.delete(f"{BASE_URL}/api/org/teams/{TestTeamsCRUD.team_id}")
        assert resp.status_code == 200

    def test_cleanup_setting(self, session):
        resp = session.delete(f"{BASE_URL}/api/org/settings/{TestTeamsCRUD.setting_id}")
        assert resp.status_code == 200


class TestMemberManagement:
    """Test member assignment/removal"""
    setting_id = None
    team_id = None
    test_user_id = None

    def test_setup(self, session):
        # Create setting and team
        s = session.post(f"{BASE_URL}/api/org/settings", json={"name": "TEST_MemberSetting"})
        assert s.status_code == 200
        TestMemberManagement.setting_id = s.json()["id"]

        t = session.post(f"{BASE_URL}/api/org/settings/{TestMemberManagement.setting_id}/teams", json={"name": "TEST_MemberTeam"})
        assert t.status_code == 200
        TestMemberManagement.team_id = t.json()["id"]

    def test_get_unassigned_users(self, session):
        resp = session.get(f"{BASE_URL}/api/org/structure")
        assert resp.status_code == 200
        unassigned = resp.json()["unassigned_users"]
        assert isinstance(unassigned, list)
        # Store a user id for member assignment test
        if unassigned:
            TestMemberManagement.test_user_id = unassigned[0]["id"]

    def test_add_member(self, session):
        if not TestMemberManagement.test_user_id:
            pytest.skip("No unassigned user available")
        resp = session.post(
            f"{BASE_URL}/api/org/teams/{TestMemberManagement.team_id}/members",
            json={"user_id": TestMemberManagement.test_user_id}
        )
        assert resp.status_code == 200

    def test_member_appears_in_team(self, session):
        if not TestMemberManagement.test_user_id:
            pytest.skip("No unassigned user available")
        resp = session.get(f"{BASE_URL}/api/org/structure")
        settings = resp.json()["settings"]
        setting = next((s for s in settings if s["id"] == TestMemberManagement.setting_id), None)
        team = next((t for t in setting.get("teams", []) if t["id"] == TestMemberManagement.team_id), None)
        member_ids = [m["id"] for m in team.get("members", [])]
        assert TestMemberManagement.test_user_id in member_ids

    def test_remove_member(self, session):
        if not TestMemberManagement.test_user_id:
            pytest.skip("No unassigned user available")
        resp = session.delete(
            f"{BASE_URL}/api/org/teams/{TestMemberManagement.team_id}/members/{TestMemberManagement.test_user_id}"
        )
        assert resp.status_code == 200

    def test_cleanup(self, session):
        session.delete(f"{BASE_URL}/api/org/settings/{TestMemberManagement.setting_id}")
