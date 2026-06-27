"""Tests for inline user editing feature - PUT /api/admin/users/{id}"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

@pytest.fixture(scope="module")
def admin_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "admin@supervision.com", "password": "Admin123!"})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json().get("token") or resp.cookies.get("token")

@pytest.fixture(scope="module")
def auth_headers(admin_token):
    if admin_token:
        return {"Authorization": f"Bearer {admin_token}"}
    return {}

@pytest.fixture(scope="module")
def test_user_id(auth_headers):
    """Get the first non-admin user's ID for testing"""
    resp = requests.get(f"{BASE_URL}/api/admin/users", headers=auth_headers)
    assert resp.status_code == 200
    users = resp.json()
    # Find a non-admin user to test with
    for u in users:
        if u.get("role") != "admin":
            return u["id"]
    return users[0]["id"]

@pytest.fixture(scope="module")
def test_user_orig(auth_headers, test_user_id):
    """Get original user data"""
    resp = requests.get(f"{BASE_URL}/api/admin/users", headers=auth_headers)
    users = resp.json()
    return next((u for u in users if u["id"] == test_user_id), None)

# GET /api/admin/users
def test_list_users(auth_headers):
    resp = requests.get(f"{BASE_URL}/api/admin/users", headers=auth_headers)
    assert resp.status_code == 200
    users = resp.json()
    assert isinstance(users, list)
    assert len(users) > 0
    print(f"PASS: list_users returned {len(users)} users")

# PUT - update name
def test_update_user_name(auth_headers, test_user_id, test_user_orig):
    new_name = "TEST_Updated Name"
    resp = requests.put(
        f"{BASE_URL}/api/admin/users/{test_user_id}",
        json={"name": new_name, "email": test_user_orig["email"], "role": test_user_orig["role"], "is_active": test_user_orig.get("is_active", True)},
        headers=auth_headers
    )
    assert resp.status_code == 200, f"Failed: {resp.text}"
    data = resp.json()
    assert "message" in data
    print(f"PASS: update_user_name -> {data}")

    # Verify by listing
    users_resp = requests.get(f"{BASE_URL}/api/admin/users", headers=auth_headers)
    users = users_resp.json()
    updated = next((u for u in users if u["id"] == test_user_id), None)
    assert updated is not None
    assert updated["name"] == new_name
    print(f"PASS: name persisted in DB: {updated['name']}")

# PUT - update active status  
def test_update_user_active_status(auth_headers, test_user_id, test_user_orig):
    current_active = test_user_orig.get("is_active", True)
    new_active = not current_active
    resp = requests.put(
        f"{BASE_URL}/api/admin/users/{test_user_id}",
        json={"name": test_user_orig["name"], "email": test_user_orig["email"], "role": test_user_orig["role"], "is_active": new_active},
        headers=auth_headers
    )
    assert resp.status_code == 200, f"Failed: {resp.text}"
    
    # Restore original
    requests.put(
        f"{BASE_URL}/api/admin/users/{test_user_id}",
        json={"is_active": current_active},
        headers=auth_headers
    )
    print(f"PASS: update_user_active_status toggled to {new_active} and restored")

# PUT - duplicate email should return 400
def test_update_user_duplicate_email(auth_headers, test_user_id):
    resp = requests.get(f"{BASE_URL}/api/admin/users", headers=auth_headers)
    users = resp.json()
    if len(users) < 2:
        pytest.skip("Need at least 2 users to test duplicate email")
    # Get another user's email
    other_user = next((u for u in users if u["id"] != test_user_id), None)
    other_email = other_user["email"]
    
    resp = requests.put(
        f"{BASE_URL}/api/admin/users/{test_user_id}",
        json={"email": other_email},
        headers=auth_headers
    )
    assert resp.status_code == 400, f"Expected 400 for duplicate email, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "already in use" in data.get("detail", "").lower()
    print(f"PASS: duplicate email correctly rejected with 400")

# PUT - restore original name after tests
def test_restore_original_user(auth_headers, test_user_id, test_user_orig):
    resp = requests.put(
        f"{BASE_URL}/api/admin/users/{test_user_id}",
        json={"name": test_user_orig["name"], "email": test_user_orig["email"], "role": test_user_orig["role"], "is_active": test_user_orig.get("is_active", True)},
        headers=auth_headers
    )
    assert resp.status_code == 200
    print(f"PASS: original user data restored")

# Non-admin cannot update users
def test_update_user_non_admin_forbidden():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "manager@supervision.com", "password": "Manager123!"})
    if resp.status_code != 200:
        pytest.skip("Manager login failed")
    manager_token = resp.json().get("token")
    headers = {"Authorization": f"Bearer {manager_token}"} if manager_token else {}
    
    # Get a user ID
    users_resp = requests.get(f"{BASE_URL}/api/admin/users", headers=headers)
    if users_resp.status_code != 200:
        pytest.skip("Cannot list users as manager")
    users = users_resp.json()
    if not users:
        pytest.skip("No users found")
    user_id = users[0]["id"]
    
    resp = requests.put(f"{BASE_URL}/api/admin/users/{user_id}", json={"name": "Hacked"}, headers=headers)
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
    print(f"PASS: non-admin PUT correctly returns 403")
