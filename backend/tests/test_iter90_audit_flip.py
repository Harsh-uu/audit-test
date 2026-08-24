"""Iteration 90 — Audit trail fixes for speaker-text saves (routers/review.py).

Covers:
  1. PII redaction false-positive fix: after a confidentiality review, the next
     speaker-label save must NOT log a fake `transcript_text_edited` entry for
     the already-completed redaction.
  2. `edit_note` passthrough: flip-from-here note is used verbatim as the
     speaker_correction detail (unicode <-> swap wording), not the confusing
     "'A' -> 'B'; 'B' -> 'A'" auto-inferred diff.
  3. Regressions: plain rename detection, genuine text-edit detection,
     split-turn save.
"""
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import asyncpg
import bcrypt
import pytest
import requests
from dotenv import dotenv_values

be = dotenv_values("/app/backend/.env")
fe = dotenv_values("/app/frontend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe["REACT_APP_BACKEND_URL"]).rstrip("/") + "/api"
DSN = be["DATABASE_URL"]

MANAGER = ("manager@supervision.com", "Manager123!")
SEED = "/app/backend/tests/seed_pii_flow.py"


# ── fixtures ─────────────────────────────────────────────────────────────────

async def _set_mfa(email):
    conn = await asyncpg.connect(DSN, ssl="require")
    h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await conn.execute(
        "UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3",
        h, exp, email)
    await conn.close()


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    email, pw = MANAGER
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    data = r.json()
    if data.get("requires_mfa"):
        asyncio.run(_set_mfa(email))
        r2 = s.post(f"{BASE}/auth/verify-mfa",
                    json={"mfa_session": data["mfa_session"], "code": "123456"}, timeout=60)
        if r2.status_code != 200:
            pytest.fail(f"mfa verify failed {r2.status_code}: {r2.text[:300]}")
    me = s.get(f"{BASE}/auth/me", timeout=60)
    assert me.status_code == 200, me.text[:200]
    return s


@pytest.fixture(scope="session")
def meeting_id():
    out = subprocess.run([sys.executable, SEED, "create"], capture_output=True, text=True, cwd="/app/backend/tests")
    assert out.returncode == 0, out.stderr[-800:]
    mid = out.stdout.strip().splitlines()[-1]
    subprocess.run([sys.executable, SEED, "analysis", mid], capture_output=True, text=True, cwd="/app/backend/tests")
    yield mid
    subprocess.run([sys.executable, SEED, "cleanup"], capture_output=True, text=True, cwd="/app/backend/tests")


def _audit(client, mid):
    r = client.get(f"{BASE}/review/{mid}/audit-trail", timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    data = r.json()
    return data["events"] if isinstance(data, dict) and "events" in data else data


def _speaker_text(client, mid):
    r = client.get(f"{BASE}/review/{mid}", timeout=60)
    assert r.status_code == 200, r.text[:300]
    return r.json()["transcript"]["speaker_text"]


def _save(client, mid, text, edit_note=None):
    body = {"speaker_text": text, "speaker_colors": None, "edit_note": edit_note}
    return client.patch(f"{BASE}/review/{mid}/speaker-text", json=body, timeout=60)


# ── tests ────────────────────────────────────────────────────────────────────

class TestAuditTrailFlipAndRedaction:

    def test_01_seed_meeting_visible(self, client, meeting_id):
        r = client.get(f"{BASE}/review/{meeting_id}", timeout=60)
        assert r.status_code == 200, r.text[:300]
        m = r.json()
        assert m["id"] == meeting_id
        assert "_id" not in m
        txt = m["transcript"]["speaker_text"]
        assert "Manager:" in txt and "Staff:" in txt
        assert "Margaret Thompson" in txt

    def test_02_complete_pii_review(self, client, meeting_id):
        payload = {"skipped": False, "redactions": [
            {"id": "r1", "original": "Margaret Thompson", "replacement": "[Service User]", "type": "name"},
            {"id": "r2", "original": "Ahmed Khan", "replacement": "[Service User 2]", "type": "name"},
        ]}
        r = client.post(f"{BASE}/review/{meeting_id}/complete-pii-review", json=payload, timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["redactions_applied"] == 2

        txt = _speaker_text(client, meeting_id)
        assert "[Service User]" in txt
        assert "Margaret Thompson" not in txt

        events = _audit(client, meeting_id)
        assert any(e["type"] == "pii_review_completed" for e in events), [e["type"] for e in events]

    def test_03_flip_after_pii_review_no_fake_text_edit(self, client, meeting_id):
        """KEY FIX 1 + 2: flip after PII review -> clean swap note, no fake text edit."""
        before_text = _speaker_text(client, meeting_id)  # redaction-applied read-time text
        turns = [l for l in before_text.strip().split("\n") if l.strip()]
        # flip Manager <-> Staff from turn 3 onwards (index 2)
        flipped = []
        for i, ln in enumerate(turns):
            if i >= 2 and ":" in ln:
                spk, body = ln.split(":", 1)
                spk = spk.strip()
                new = "Staff" if spk == "Manager" else ("Manager" if spk == "Staff" else spk)
                flipped.append(f"{new}:{body}")
            else:
                flipped.append(ln)
        new_text = "\n".join(flipped)
        note = "Speakers flipped from Turn 3 onwards: 'Manager' \u2194 'Staff'"

        before_events = _audit(client, meeting_id)
        r = _save(client, meeting_id, new_text, edit_note=note)
        assert r.status_code == 200, r.text[:300]

        events = _audit(client, meeting_id)
        new_events = events[len(before_events):] if len(events) > len(before_events) else events
        # Find the newest speaker_correction
        sc = [e for e in events if e["type"] == "speaker_correction"]
        assert sc, "no speaker_correction audit entry"
        latest = next((e for e in sc if e["detail"] == note), None)
        assert latest is not None, f"flip note not found; speaker_correction details={[e['detail'] for e in sc]}"
        assert latest["label"] == "Speaker labels edited"
        assert "\u2194" in latest["detail"]
        assert "\u2192" not in latest["detail"], "swap should not be described with one-way arrows"

        # No fake transcript_text_edited mentioning the redacted name
        text_edits = [e for e in events if e["type"] == "transcript_text_edited"]
        bad = [e for e in text_edits if "Margaret Thompson" in e["detail"] or "[Service User]" in e["detail"]]
        assert not bad, f"redaction leaked into text-edit audit entry: {bad}"
        assert not text_edits, f"unexpected transcript_text_edited entries for a pure flip: {[e['detail'] for e in text_edits]}"

    def test_04_flip_persisted(self, client, meeting_id):
        txt = _speaker_text(client, meeting_id)
        lines = [l for l in txt.strip().split("\n") if l.strip()]
        assert lines[2].startswith("Staff:"), lines[2][:60]
        assert lines[0].startswith("Manager:"), lines[0][:60]

    def test_05_regression_plain_rename(self, client, meeting_id):
        txt = _speaker_text(client, meeting_id)
        new_text = "\n".join(
            ("Line Manager:" + l.split(":", 1)[1]) if l.startswith("Manager:") else l
            for l in txt.strip().split("\n") if l.strip()
        )
        r = _save(client, meeting_id, new_text)  # no edit_note
        assert r.status_code == 200, r.text[:300]
        events = _audit(client, meeting_id)
        sc = [e for e in events if e["type"] == "speaker_correction"]
        assert any("Speaker labels updated:" in e["detail"] and "'Manager'" in e["detail"]
                   and "'Line Manager'" in e["detail"] for e in sc), [e["detail"] for e in sc]
        text_edits = [e for e in events if e["type"] == "transcript_text_edited"]
        assert not text_edits, f"rename should not produce text edits: {[e['detail'] for e in text_edits]}"

    def test_06_regression_text_edit(self, client, meeting_id):
        txt = _speaker_text(client, meeting_id)
        lines = [l for l in txt.strip().split("\n") if l.strip()]
        original_first = lines[0]
        lines[0] = original_first.rstrip(".") + " TEST_EDIT_SUFFIX."
        r = _save(client, meeting_id, "\n".join(lines))
        assert r.status_code == 200, r.text[:300]
        events = _audit(client, meeting_id)
        te = [e for e in events if e["type"] == "transcript_text_edited"]
        assert te, "no transcript_text_edited entry for a genuine text edit"
        assert "TEST_EDIT_SUFFIX" in te[0]["detail"], te[0]["detail"]
        assert te[0]["label"] == "Transcript text edited"
        # persisted
        assert "TEST_EDIT_SUFFIX" in _speaker_text(client, meeting_id)

    def test_07_regression_split_turn(self, client, meeting_id):
        txt = _speaker_text(client, meeting_id)
        lines = [l for l in txt.strip().split("\n") if l.strip()]
        before_count = len(lines)
        spk, body = lines[1].split(":", 1)
        body = body.strip()
        mid_i = len(body) // 2
        cut = body.rfind(" ", 0, mid_i)
        lines[1:2] = [f"{spk}: {body[:cut].strip()}", f"{spk}: {body[cut:].strip()}"]
        r = _save(client, meeting_id, "\n".join(lines))
        assert r.status_code == 200, r.text[:300]
        after = [l for l in _speaker_text(client, meeting_id).strip().split("\n") if l.strip()]
        assert len(after) == before_count + 1, f"{before_count} -> {len(after)}"

    def test_08_no_edit_note_no_stale_note(self, client, meeting_id):
        """Discard-equivalent: a later unrelated save with edit_note=None must
        not re-use a previous flip note."""
        txt = _speaker_text(client, meeting_id)
        r = _save(client, meeting_id, txt, edit_note=None)
        assert r.status_code == 200, r.text[:300]
        events = _audit(client, meeting_id)
        sc = [e for e in events if e["type"] == "speaker_correction"]
        assert "\u2194" not in sc[0]["detail"], f"stale flip note reappeared: {sc[0]['detail']}"
        assert sc[0]["detail"] in ("Speaker labels saved", "Speaker colours updated"), sc[0]["detail"]

    def test_09_restore_backup_and_reset(self, client, meeting_id):
        r = client.post(f"{BASE}/review/{meeting_id}/speaker-text/restore-backup", json={}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        events = _audit(client, meeting_id)
        assert any(e["type"] == "speaker_restore_backup" for e in events), [e["type"] for e in events]

        r = client.delete(f"{BASE}/review/{meeting_id}/speaker-text", timeout=60)
        assert r.status_code == 200, r.text[:300]
        events = _audit(client, meeting_id)
        assert any(e["type"] == "speaker_reset" for e in events), [e["type"] for e in events]

    def test_10_locked_report_rejects_save(self, client, meeting_id):
        conn_txt = _speaker_text(client, meeting_id)
        subprocess.run([sys.executable, SEED, "status", meeting_id, "signed_off"],
                       capture_output=True, text=True, cwd="/app/backend/tests")
        try:
            r = _save(client, meeting_id, conn_txt or "Manager: x", edit_note="test")
            assert r.status_code == 409, f"expected 409, got {r.status_code} {r.text[:200]}"
        finally:
            subprocess.run([sys.executable, SEED, "status", meeting_id, "in_review"],
                           capture_output=True, text=True, cwd="/app/backend/tests")

    @pytest.mark.xfail(reason="KNOWN BUG (iter90): Split Turn shifts turn indices, so the "
                              "position-by-position diff reports every following turn as "
                              "'transcript text edited' plus a contradictory rename pair. "
                              "Same 'nonsense audit entry' class as the flip bug; needs an "
                              "edit_note (or index-aware diff) for the split path too.",
                       strict=False)
    def test_11_split_turn_should_not_produce_nonsense_audit(self, client, meeting_id):
        # Re-seed a clean speaker_text (previous tests reset it)
        base = "\n".join([
            "Manager: Thanks for coming in today.",
            "Staff: Busy week, lots going on and plenty to update you on.",
            "Manager: Anything to escalate?",
            "Staff: No, all recorded.",
        ])
        assert _save(client, meeting_id, base).status_code == 200
        lines = base.split("\n")
        spk, body = lines[1].split(":", 1)
        body = body.strip()
        cut = body.rfind(" ", 0, len(body) // 2)
        lines[1:2] = [f"{spk}: {body[:cut].strip()}", f"{spk}: {body[cut:].strip()}"]
        assert _save(client, meeting_id, "\n".join(lines)).status_code == 200

        events = _audit(client, meeting_id)
        newest_text_edits = [e for e in events if e["type"] == "transcript_text_edited"]
        newest_sc = [e for e in events if e["type"] == "speaker_correction"]
        assert not (newest_text_edits and "Anything to escalate" in newest_text_edits[0]["detail"]), \
            f"split turn logged shifted turns as text edits: {newest_text_edits[0]['detail'][:200]}"
        assert "\u2192" not in newest_sc[0]["detail"] or "updated" not in newest_sc[0]["detail"], \
            f"split turn logged a bogus rename: {newest_sc[0]['detail'][:200]}"
