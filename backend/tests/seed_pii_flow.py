"""
Seed / manipulate a test meeting to exercise the new PII-gate-during-analysis flow.

Usage:
  python seed_pii_flow.py create           -> creates TEST_ meeting in status 'analyzing' with transcript
  python seed_pii_flow.py status <id> <st> -> sets meeting status
  python seed_pii_flow.py analysis <id>    -> inserts analysis + sets status in_review
  python seed_pii_flow.py fail <id>        -> sets status processing_failed
  python seed_pii_flow.py show <id>        -> prints key fields
  python seed_pii_flow.py cleanup          -> deletes all TEST_PII meetings + children
  python seed_pii_flow.py mfa <email>      -> sets mfa_code to bcrypt('123456')
"""
import asyncio, json, os, sys, uuid
from datetime import datetime, timezone, timedelta
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
DSN = os.environ["DATABASE_URL"]

TRANSCRIPT = (
    "Manager: Thanks for coming in today. How have things been on the unit?\n"
    "Staff: Busy. I have been supporting Margaret Thompson with her personal care and she has been refusing "
    "her medication a few times this week.\n"
    "Manager: Did you record that in the MAR chart and escalate to the nurse?\n"
    "Staff: Yes, and I also called her son Peter on 07700 900123 to let him know.\n"
    "Manager: Good. Anything about safeguarding you want to raise?\n"
    "Staff: I was worried about a bruise on Mr Ahmed Khan's arm at 42 Rosewood Avenue, I filled in a body map "
    "and reported it to the safeguarding lead.\n"
    "Manager: Well done, that is exactly right. Let us talk about your training needs.\n"
    "Staff: I would like to do the dementia awareness refresher and my moving and handling is due.\n"
    "Manager: I will book both. Any wellbeing concerns?\n"
    "Staff: I am fine, just tired from the extra shifts.\n"
)


async def main():
    cmd = sys.argv[1]
    conn = await asyncpg.connect(DSN, ssl="require")
    now = datetime.now(timezone.utc).isoformat()
    try:
        if cmd == "create":
            mgr = await conn.fetchrow("SELECT id, name, org_id FROM users WHERE email='manager@supervision.com'")
            staff = await conn.fetchrow("SELECT id, name, email FROM users WHERE email='user@supervision.com'")
            assert mgr and staff, "test users missing"
            mid = str(uuid.uuid4())
            tid = str(uuid.uuid4())
            attendees = [
                {"user_id": staff["id"], "name": staff["name"], "email": staff["email"], "role": "supervisee", "reviewed": False},
                {"user_id": mgr["id"], "name": mgr["name"], "email": "manager@supervision.com", "role": "manager", "reviewed": False},
            ]
            await conn.execute(
                """INSERT INTO meetings (id, org_id, title, date, location, meeting_type, created_by,
                   created_by_name, sign_off_manager_id, sign_off_manager_name, attendees, status,
                   transcript_id, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,'supervision',$6,$7,$6,$7,$8::jsonb,'analyzing',$9,$10,$10)""",
                mid, mgr["org_id"], "TEST_PII Flow Supervision", now, "Test Room",
                mgr["id"], mgr["name"], json.dumps(attendees), tid, now,
            )
            await conn.execute(
                "INSERT INTO transcripts (id, meeting_id, org_id, text, speaker_text, created_at) VALUES ($1,$2,$3,$4,$5,$6)",
                tid, mid, mgr["org_id"], TRANSCRIPT, TRANSCRIPT, now,
            )
            print(mid)
        elif cmd == "status":
            await conn.execute("UPDATE meetings SET status=$1 WHERE id=$2", sys.argv[3], sys.argv[2])
            print("ok")
        elif cmd == "analysis":
            mid = sys.argv[2]
            m = await conn.fetchrow("SELECT org_id FROM meetings WHERE id=$1", mid)
            aid = str(uuid.uuid4())
            await conn.execute(
                """INSERT INTO analyses (id, meeting_id, org_id, summary, achievements, actions,
                   learning_needs, risks, cqc_mappings, created_at)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8::jsonb,$9::jsonb,$10)""",
                aid, mid, m["org_id"],
                "Supervision covered medication refusal, a safeguarding body-map referral and training needs.",
                json.dumps([{"description": "Correctly escalated a safeguarding concern"}]),
                json.dumps([{"text": "Book dementia awareness refresher", "owner": "Manager", "due_date": "2026-08-01", "status": "open"}]),
                json.dumps([{"text": "Moving and handling refresher due"}]),
                json.dumps([{"text": "Repeated medication refusal", "severity": "medium"}]),
                json.dumps([{"standard_code": "Safe", "standard_name": "Safe", "evidence": "Body map completed and safeguarding lead informed", "transcript_excerpt": "I filled in a body map"}]),
                now,
            )
            await conn.execute("UPDATE meetings SET analysis_id=$1, status='in_review', updated_at=$2 WHERE id=$3", aid, now, mid)
            print("ok")
        elif cmd == "fail":
            await conn.execute("UPDATE meetings SET status='processing_failed' WHERE id=$1", sys.argv[2])
            print("ok")
        elif cmd == "show":
            r = await conn.fetchrow("SELECT id,status,transcript_id,analysis_id,pii_review_status,pii_skipped,pii_redactions FROM meetings WHERE id=$1", sys.argv[2])
            print(dict(r) if r else "not found")
        elif cmd == "reset_pii":
            await conn.execute("UPDATE meetings SET pii_review_status=NULL, pii_redactions='[]'::jsonb, pii_skipped=NULL WHERE id=$1", sys.argv[2])
            print("ok")
        elif cmd == "cleanup":
            rows = await conn.fetch("SELECT id FROM meetings WHERE title LIKE 'TEST_PII%'")
            for r in rows:
                for t in ["transcripts", "analyses", "audio_files", "reviewer_comments", "review_edits", "audit_logs"]:
                    try:
                        await conn.execute(f"DELETE FROM {t} WHERE meeting_id=$1", r["id"])
                    except Exception:
                        pass
                await conn.execute("DELETE FROM meetings WHERE id=$1", r["id"])
            print(f"deleted {len(rows)}")
        elif cmd == "mfa":
            import bcrypt
            h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
            exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
            await conn.execute("UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3", h, exp, sys.argv[2])
            print("mfa set")
        elif cmd == "mfa_loop":
            import bcrypt
            email = sys.argv[2]
            secs = int(sys.argv[3]) if len(sys.argv) > 3 else 180
            end = datetime.now(timezone.utc) + timedelta(seconds=secs)
            h = bcrypt.hashpw(b"123456", bcrypt.gensalt()).decode()
            while datetime.now(timezone.utc) < end:
                exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
                await conn.execute("UPDATE users SET mfa_code=$1, mfa_code_expires_at=$2, mfa_code_attempts=0 WHERE email=$3", h, exp, email)
                await asyncio.sleep(2)
            print("loop done")
    finally:
        await conn.close()


asyncio.run(main())
