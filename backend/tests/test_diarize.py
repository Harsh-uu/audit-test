"""Tests for speaker diarization feature - POST /api/processing/{id}/diarize"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MEETING_ID = "6a3f92df95f60e56302d0d5e"

@pytest.fixture(scope="module")
def token():
    res = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "manager@supervision.com", "password": "Manager123!"})
    assert res.status_code == 200, f"Login failed: {res.text}"
    return res.json().get("token") or res.cookies.get("token")

@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}

# Test 1: diarize endpoint returns speaker_text
def test_diarize_returns_speaker_text(auth_headers):
    res = requests.post(f"{BASE_URL}/api/processing/{MEETING_ID}/diarize", headers=auth_headers, json={})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert "speaker_text" in data, "Response missing speaker_text"
    assert data["speaker_text"], "speaker_text is empty"
    # Check Manager:/Worker: labels
    text = data["speaker_text"]
    has_label = any(f"{label}:" in text for label in ["Manager", "Worker", "Supervisor"])
    assert has_label, f"No Manager/Worker labels found in speaker_text: {text[:200]}"
    print(f"PASS: speaker_text has {len(text)} chars, first 200: {text[:200]}")

# Test 2: After diarize, GET /api/review/{meeting_id} returns speaker_text
def test_review_returns_speaker_text_after_diarize(auth_headers):
    # First ensure diarize has been called
    res = requests.post(f"{BASE_URL}/api/processing/{MEETING_ID}/diarize", headers=auth_headers, json={})
    assert res.status_code == 200
    
    # Now check review endpoint
    review_res = requests.get(f"{BASE_URL}/api/review/{MEETING_ID}", headers=auth_headers)
    assert review_res.status_code == 200, f"Review endpoint failed: {review_res.text}"
    data = review_res.json()
    transcript = data.get("transcript") or {}
    assert transcript.get("speaker_text"), f"speaker_text not in review response: {list(transcript.keys())}"
    print(f"PASS: review transcript has speaker_text: {str(transcript['speaker_text'])[:100]}")

# Test 3: Invalid meeting ID returns 400
def test_diarize_invalid_id(auth_headers):
    res = requests.post(f"{BASE_URL}/api/processing/invalid_id/diarize", headers=auth_headers, json={})
    assert res.status_code == 400

# Test 4: Non-existent meeting returns 404
def test_diarize_nonexistent_meeting(auth_headers):
    res = requests.post(f"{BASE_URL}/api/processing/000000000000000000000000/diarize", headers=auth_headers, json={})
    assert res.status_code == 404
