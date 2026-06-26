"""
Tests for the comments fix: GET /api/meetings/{id} must include 'comments' array.
Covers: POST comment, GET meeting with comments, multiple comments ordering.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


def get_admin_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@supervision.com",
        "password": "Admin123!"
    })
    assert resp.status_code == 200, f"Admin login failed: {resp.text}"
    return resp.json().get("token") or resp.cookies.get("supervision_token")


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def admin_token():
    return get_admin_token()


@pytest.fixture(scope="module")
def test_meeting(admin_token):
    """Create a test meeting for comment tests"""
    resp = requests.post(
        f"{BASE_URL}/api/meetings/",
        json={"title": "TEST_Comments Fix Meeting", "date": "2026-02-20", "meeting_type": "supervision"},
        headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200, f"Create meeting failed: {resp.text}"
    meeting = resp.json()
    yield meeting
    # Cleanup
    requests.delete(f"{BASE_URL}/api/meetings/{meeting['id']}", headers=auth_headers(admin_token))


class TestCommentsEndpoint:
    """POST /api/review/{meeting_id}/comments"""

    def test_post_comment_returns_correct_fields(self, admin_token, test_meeting):
        """POST comment returns user_name, text, created_at"""
        resp = requests.post(
            f"{BASE_URL}/api/review/{test_meeting['id']}/comments",
            json={"text": "TEST_First comment"},
            headers=auth_headers(admin_token)
        )
        assert resp.status_code == 200, f"Post comment failed: {resp.text}"
        data = resp.json()
        assert "user_name" in data, "user_name missing from comment response"
        assert "text" in data, "text missing from comment response"
        assert "created_at" in data, "created_at missing from comment response"
        assert data["text"] == "TEST_First comment"
        print("PASS: POST comment returns user_name, text, created_at")

    def test_post_comment_has_meeting_id(self, admin_token, test_meeting):
        """POST comment response includes meeting_id"""
        resp = requests.post(
            f"{BASE_URL}/api/review/{test_meeting['id']}/comments",
            json={"text": "TEST_Second comment"},
            headers=auth_headers(admin_token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("meeting_id") == test_meeting["id"]
        print("PASS: POST comment includes meeting_id")


class TestGetMeetingIncludesComments:
    """GET /api/meetings/{id} must include comments array"""

    def test_get_meeting_has_comments_key(self, admin_token, test_meeting):
        """GET meeting response has 'comments' key"""
        resp = requests.get(
            f"{BASE_URL}/api/meetings/{test_meeting['id']}",
            headers=auth_headers(admin_token)
        )
        assert resp.status_code == 200, f"Get meeting failed: {resp.text}"
        data = resp.json()
        assert "comments" in data, "BUG: 'comments' key missing from GET /api/meetings/{id} response"
        assert isinstance(data["comments"], list), "'comments' must be a list"
        print("PASS: GET meeting includes 'comments' array")

    def test_get_meeting_comments_contain_posted_comment(self, admin_token, test_meeting):
        """Comments posted should appear in GET meeting response"""
        # Post a unique comment
        unique_text = "TEST_Verification comment unique 12345"
        requests.post(
            f"{BASE_URL}/api/review/{test_meeting['id']}/comments",
            json={"text": unique_text},
            headers=auth_headers(admin_token)
        )
        # Get meeting and verify comment appears
        resp = requests.get(
            f"{BASE_URL}/api/meetings/{test_meeting['id']}",
            headers=auth_headers(admin_token)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "comments" in data
        texts = [c.get("text") for c in data["comments"]]
        assert unique_text in texts, f"Posted comment not found in meeting comments. Got: {texts}"
        print(f"PASS: Comment appears in GET meeting response. Total comments: {len(data['comments'])}")

    def test_comments_have_required_fields(self, admin_token, test_meeting):
        """Each comment in GET meeting response must have user_name and created_at"""
        resp = requests.get(
            f"{BASE_URL}/api/meetings/{test_meeting['id']}",
            headers=auth_headers(admin_token)
        )
        assert resp.status_code == 200
        data = resp.json()
        for c in data["comments"]:
            assert "user_name" in c, f"user_name missing in comment: {c}"
            assert "created_at" in c, f"created_at missing in comment: {c}"
            assert "text" in c, f"text missing in comment: {c}"
        print("PASS: All comments have user_name, text, created_at")

    def test_comments_chronological_order(self, admin_token, test_meeting):
        """Multiple comments should appear in ascending chronological order"""
        # Post two more comments with slight delay handled by server timestamps
        for i in range(2):
            requests.post(
                f"{BASE_URL}/api/review/{test_meeting['id']}/comments",
                json={"text": f"TEST_Order comment {i}"},
                headers=auth_headers(admin_token)
            )

        resp = requests.get(
            f"{BASE_URL}/api/meetings/{test_meeting['id']}",
            headers=auth_headers(admin_token)
        )
        assert resp.status_code == 200
        data = resp.json()
        comments = data["comments"]
        if len(comments) >= 2:
            timestamps = [c["created_at"] for c in comments]
            assert timestamps == sorted(timestamps), f"Comments not in chronological order: {timestamps}"
        print(f"PASS: {len(comments)} comments in chronological order")
