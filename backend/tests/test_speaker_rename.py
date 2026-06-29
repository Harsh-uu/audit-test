"""
Backend tests for speaker-text PATCH endpoint and speaker rename persistence.
Testing the bug fix: staged renames applied synchronously before serialization.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

MEETING_ID = "6a3f7df3e7e639d39c4915df"  # Full meeting with Steve Mika 2 (103 turns)
MEETING_ID_106 = "6a3f92df95f60e56302d0d5e"  # Full meetin Steve Steve Mika 1 (new) - restored 106 turns

ADMIN_EMAIL = "admin@supervision.com"
ADMIN_PASSWORD = "Admin123!"


@pytest.fixture(scope="module")
def auth_token():
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json().get("access_token") or resp.json().get("token")


@pytest.fixture(scope="module")
def headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(scope="module")
def original_speaker_text(headers):
    """Get and preserve the original speaker_text for restoration."""
    resp = requests.get(f"{BASE_URL}/api/review/{MEETING_ID}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    return data.get("transcript", {}).get("speaker_text", "")


def test_meeting_loads(headers):
    """Meeting 6a3f7df3e7e639d39c4915df should exist and have speaker_text."""
    resp = requests.get(f"{BASE_URL}/api/review/{MEETING_ID}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("transcript", {}).get("speaker_text"), "speaker_text should be present"
    turns = [l for l in data["transcript"]["speaker_text"].split("\n") if l.strip()]
    print(f"Meeting has {len(turns)} turns in speaker_text")
    assert len(turns) >= 100, f"Expected ~103 turns, got {len(turns)}"


def test_meeting_106_turns(headers):
    """Meeting 6a3f92df95f60e56302d0d5e should have 106 turns all labelled 'Speaker'."""
    resp = requests.get(f"{BASE_URL}/api/review/{MEETING_ID_106}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    speaker_text = data.get("transcript", {}).get("speaker_text", "")
    assert speaker_text, "speaker_text should be present"
    turns = [l.strip() for l in speaker_text.split("\n") if l.strip()]
    print(f"Meeting 106 has {len(turns)} turns")
    assert len(turns) == 106, f"Expected 106 turns, got {len(turns)}"
    # All turns should start with "Speaker:"
    speaker_turns = [t for t in turns if t.startswith("Speaker:")]
    assert len(speaker_turns) == 106, f"Expected all 106 turns labelled 'Speaker', got {len(speaker_turns)}"


def test_patch_speaker_text_rename(headers, original_speaker_text):
    """Simulate the staged rename fix: rename Speaker 1 -> Alice in the text and save."""
    assert original_speaker_text, "Need original speaker_text to test"
    
    # Parse turns
    turns = []
    for line in original_speaker_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        match_idx = stripped.find(":")
        if match_idx > 0 and match_idx <= 50:
            speaker = stripped[:match_idx].strip()
            text = stripped[match_idx+1:].strip()
            turns.append({"speaker": speaker, "text": text})
    
    original_count = len(turns)
    print(f"Original turns: {original_count}")
    assert original_count >= 100
    
    # Get unique speakers
    speakers = list(dict.fromkeys(t["speaker"] for t in turns))
    print(f"Speakers: {speakers[:5]}")
    
    # Simulate staged rename: Speaker 1 -> Alice (or first speaker found)
    speaker_to_rename = speakers[0]
    renamed_turns = [
        {"speaker": "Alice" if t["speaker"] == speaker_to_rename else t["speaker"], "text": t["text"]}
        for t in turns
    ]
    
    new_text = "\n".join(f"{t['speaker']}: {t['text']}" for t in renamed_turns)
    
    # PATCH
    resp = requests.patch(
        f"{BASE_URL}/api/review/{MEETING_ID}/speaker-text",
        json={"speaker_text": new_text},
        headers=headers
    )
    assert resp.status_code == 200, f"PATCH failed: {resp.text}"
    
    # Verify: GET and check
    get_resp = requests.get(f"{BASE_URL}/api/review/{MEETING_ID}", headers=headers)
    assert get_resp.status_code == 200
    saved_text = get_resp.json().get("transcript", {}).get("speaker_text", "")
    saved_turns = [l.strip() for l in saved_text.split("\n") if l.strip()]
    
    # Check count preserved
    assert len(saved_turns) == original_count, f"Turn count changed: {original_count} -> {len(saved_turns)}"
    
    # Check Alice appears
    assert any("Alice:" in t for t in saved_turns), "Alice should appear in saved turns"
    # Check old speaker label does NOT appear
    assert not any(t.startswith(f"{speaker_to_rename}:") for t in saved_turns), \
        f"Original speaker '{speaker_to_rename}' should not appear after rename"
    
    print(f"Rename test passed. {original_count} turns preserved. 'Alice' found in saved text.")


def test_restore_original_speaker_text(headers, original_speaker_text):
    """Restore original speaker_text after rename tests."""
    resp = requests.patch(
        f"{BASE_URL}/api/review/{MEETING_ID}/speaker-text",
        json={"speaker_text": original_speaker_text},
        headers=headers
    )
    assert resp.status_code == 200, f"Restore failed: {resp.text}"
    print("Original speaker_text restored successfully.")


def test_all_turns_preserved_after_dual_rename(headers, original_speaker_text):
    """Both renames (Speaker 1->Alice, Speaker 2->Bob) preserved with full turn count."""
    turns = []
    for line in original_speaker_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        match_idx = stripped.find(":")
        if match_idx > 0 and match_idx <= 50:
            turns.append({"speaker": stripped[:match_idx].strip(), "text": stripped[match_idx+1:].strip()})
    
    original_count = len(turns)
    speakers = list(dict.fromkeys(t["speaker"] for t in turns))
    
    rename_map = {}
    if len(speakers) >= 1:
        rename_map[speakers[0]] = "Alice"
    if len(speakers) >= 2:
        rename_map[speakers[1]] = "Bob"
    
    renamed_turns = [
        {"speaker": rename_map.get(t["speaker"], t["speaker"]), "text": t["text"]}
        for t in turns
    ]
    new_text = "\n".join(f"{t['speaker']}: {t['text']}" for t in renamed_turns)
    
    resp = requests.patch(
        f"{BASE_URL}/api/review/{MEETING_ID}/speaker-text",
        json={"speaker_text": new_text},
        headers=headers
    )
    assert resp.status_code == 200
    
    get_resp = requests.get(f"{BASE_URL}/api/review/{MEETING_ID}", headers=headers)
    saved_text = get_resp.json().get("transcript", {}).get("speaker_text", "")
    saved_turns = [l.strip() for l in saved_text.split("\n") if l.strip()]
    
    assert len(saved_turns) == original_count, f"Turn count mismatch: {original_count} -> {len(saved_turns)}"
    
    if "Alice" in rename_map.values():
        assert any("Alice:" in t for t in saved_turns)
    if "Bob" in rename_map.values():
        assert any("Bob:" in t for t in saved_turns)
    
    print(f"Dual rename test passed. {original_count} turns preserved with Alice and Bob.")
    
    # Restore
    resp2 = requests.patch(
        f"{BASE_URL}/api/review/{MEETING_ID}/speaker-text",
        json={"speaker_text": original_speaker_text},
        headers=headers
    )
    assert resp2.status_code == 200
    print("Restored after dual rename test.")
