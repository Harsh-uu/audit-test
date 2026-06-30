"""Tests for Org Structure new endpoints: assign-team and invite-user"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

MANAGER_EMAIL = "manager@supervision.com"
MANAGER_PASSWORD = "Manager123!"
ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASSWORD = "Admin123!"

@pytest.fixture(scope="module")
def manager_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": MANAGER_EMAIL, "password": MANAGER_PASSWORD})
    assert r.status_code == 200
    return r.json().get("token")

@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    return r.json().get("token")

def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}

class TestOrgStructure:
    """Test org structure API endpoints"""

    def test_get_org_structure(self, manager_token):
        r = requests.get(f"{BASE_URL}/api/org/structure", headers=auth_headers(manager_token))
        assert r.status_code == 200
        data = r.json()
        assert "settings" in data
        assert "unassigned_users" in data
        print(f"PASS: GET /api/org/structure - {len(data['settings'])} settings, {len(data['unassigned_users'])} unassigned")

    def test_get_org_structure_returns_user_details(self, manager_token):
        """Verify unassigned users have name and role fields"""
        r = requests.get(f"{BASE_URL}/api/org/structure", headers=auth_headers(manager_token))
        assert r.status_code == 200
        data = r.json()
        for u in data['unassigned_users']:
            assert 'name' in u
            assert 'role' in u
            assert 'id' in u
        print(f"PASS: Unassigned users have name/role/id fields")

    def test_invite_user_manager_can_create(self, manager_token):
        """POST /api/org/invite-user - manager creates a new user"""
        import time
        payload = {
            "name": "TEST_InviteUser Org",
            "email": f"test_inviteorg_{int(time.time())}@example.com",
            "password": "TestPass123!",
            "role": "attendee"
        }
        r = requests.post(f"{BASE_URL}/api/org/invite-user", json=payload, headers=auth_headers(manager_token))
        assert r.status_code in [200, 201], f"Expected 200/201, got {r.status_code}: {r.text}"
        data = r.json()
        assert "id" in data or "user" in data or "message" in data
        print(f"PASS: POST /api/org/invite-user - user created: {r.status_code}")

    def test_invite_user_duplicate_email_fails(self, manager_token):
        """Duplicate email should return 400"""
        payload = {
            "name": "TEST_Dupe",
            "email": "test_inviteorg_unique@example.com",
            "password": "TestPass123!",
            "role": "attendee"
        }
        r = requests.post(f"{BASE_URL}/api/org/invite-user", json=payload, headers=auth_headers(manager_token))
        assert r.status_code == 400
        print(f"PASS: Duplicate email returns 400")

    def test_assign_team_invalid_user(self, manager_token):
        """PATCH /api/org/users/{id}/assign-team with invalid user id returns 404"""
        r = requests.patch(
            f"{BASE_URL}/api/org/users/000000000000000000000000/assign-team",
            json={"team_id": None},
            headers=auth_headers(manager_token)
        )
        assert r.status_code == 404
        print(f"PASS: Invalid user returns 404")

    def test_assign_team_unassign_user(self, manager_token):
        """Unassign a user by sending team_id: null"""
        r = requests.get(f"{BASE_URL}/api/org/structure", headers=auth_headers(manager_token))
        assert r.status_code == 200
        data = r.json()
        unassigned = data.get('unassigned_users', [])
        if not unassigned:
            pytest.skip("No unassigned users to test")
        user_id = unassigned[0]['id']
        r2 = requests.patch(
            f"{BASE_URL}/api/org/users/{user_id}/assign-team",
            json={"team_id": None},
            headers=auth_headers(manager_token)
        )
        assert r2.status_code == 200
        print(f"PASS: Unassign user (team_id=null) returns 200")

    def test_assign_team_to_team(self, manager_token):
        """Assign a user to a team if teams exist"""
        r = requests.get(f"{BASE_URL}/api/org/structure", headers=auth_headers(manager_token))
        assert r.status_code == 200
        data = r.json()
        unassigned = data.get('unassigned_users', [])
        team_id = None
        for s in data.get('settings', []):
            for t in s.get('teams', []):
                team_id = t['id']
                break
            if team_id:
                break
        if not unassigned or not team_id:
            pytest.skip("Need unassigned users and teams to test assignment")
        user_id = unassigned[0]['id']
        r2 = requests.patch(
            f"{BASE_URL}/api/org/users/{user_id}/assign-team",
            json={"team_id": team_id},
            headers=auth_headers(manager_token)
        )
        assert r2.status_code == 200
        print(f"PASS: Assign user to team returns 200")
        # Revert
        requests.patch(
            f"{BASE_URL}/api/org/users/{user_id}/assign-team",
            json={"team_id": None},
            headers=auth_headers(manager_token)
        )

    def test_invite_user_unauthenticated_fails(self):
        """Unauthenticated request should return 401"""
        r = requests.post(f"{BASE_URL}/api/org/invite-user", json={"name": "X", "email": "x@x.com", "password": "pass1234", "role": "attendee"})
        assert r.status_code == 401
        print(f"PASS: Unauthenticated returns 401")
