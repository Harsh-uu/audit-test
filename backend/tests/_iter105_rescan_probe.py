"""Iter105 side-effect probe: does POST /api/processing/{id}/retranscribe behave
sensibly once the audio has been GDPR-purged from storage?"""
import asyncio, json, sys, time
from datetime import datetime, timedelta, timezone
sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/backend/tests")
from test_iter105_audio_gdpr_delete import (  # noqa: E402
    BASE, login, db, create_meeting, cleanup_meeting, run_sweep, backdate_grace,
    meeting_state, storage_exists)

admin = login("admin@supervision.com", "Admin123!")
manager = login("manager@supervision.com", "Manager123!")
jane = login("jane@supervision.com", "Jane123!")
jane_id = db(lambda c: c.fetchval("SELECT id FROM users WHERE email='jane@supervision.com'"))

m = create_meeting(admin, [jane_id], "probe_rescan")
mid, path = m["mid"], m["path"]
try:
    jane.post(f"{BASE}/review/{mid}/mark-reviewed", timeout=90)
    db(lambda c: c.execute("UPDATE meetings SET status='reviewed' WHERE id=$1", mid))
    print("signoff:", manager.post(f"{BASE}/review/{mid}/signoff", timeout=90).status_code)
    backdate_grace(mid, 30)
    run_sweep()
    print("state after sweep:", meeting_state(mid), "storage_exists:", storage_exists(path))

    r = manager.post(f"{BASE}/processing/{mid}/retranscribe", timeout=90)
    print("retranscribe ->", r.status_code, r.text[:250])
    time.sleep(8)
    print("diarize_status:", db(lambda c: c.fetchval("SELECT diarize_status FROM meetings WHERE id=$1", mid)))

    # audio status surfaced to the UI
    r = manager.get(f"{BASE}/processing/{mid}/status", timeout=90)
    print("status ->", r.status_code, r.text[:300])
    # transcript intact?
    r = manager.get(f"{BASE}/meetings/{mid}/transcript-text", timeout=90)
    print("transcript-text ->", r.status_code, len(r.text))
finally:
    cleanup_meeting(m)
    print("cleaned")
