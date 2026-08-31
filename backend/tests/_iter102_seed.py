"""Seed / cleanup fixtures for iteration 102 (N+1 batching regression tests).

Usage: python _iter102_seed.py seed | cleanup
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
DSN = os.environ["DATABASE_URL"]

ORG = "b00bf04f-a1b9-4673-8430-b4a08ba15d6c"
SETTING_ONE = "70591fed-9a98-4d09-a16a-b911735c63e4"  # "Team one"

MARIA = {"user_id": "f742ddf2-bfb5-44e5-8cd8-14eebb2d0cc4", "name": "Maria Santos"}
DIANE = {"user_id": "2412f428-8452-42ad-9905-d0cf9341ac30", "name": "Diane Fletcher"}
JANE = {"user_id": "724367a3-1ca9-498b-890b-0516b2f122f5", "name": "Jane Smith"}
MANAGER = {"user_id": "465c5101-bbc8-4f26-adaa-c906d3324dd5", "name": "Demo Manager"}
ADMIN_ID = "f72ac550-e6b8-4ffc-b2da-46a54a4c06d5"

P = "TEST_iter102_"
M1, M2, M3, M4 = [f"{P}m{i}" for i in (1, 2, 3, 4)]
A1, A2, A3 = [f"{P}a{i}" for i in (1, 2, 3)]
T1, T2, T3 = [f"{P}t{i}" for i in (1, 2, 3)]
DANGLING_A = f"{P}missing_analysis"
DANGLING_T = f"{P}missing_transcript"
TEAM_A, TEAM_B = f"{P}teamA", f"{P}teamB"
REVIEWER_ID = f"{P}reviewer"

NOW = datetime.now(timezone.utc).isoformat()

ANALYSES = {
    A1: {
        "cqc": [{"regulation_ref": "R9", "regulation_name": "Person-centred care",
                 "confidence": "high", "status": "accepted",
                 "evidence_summary": "ITER102A1CQC evidence about Maria Santos"}],
        "cc": [{"standard_ref": "CC1", "standard_name": "Understand your role",
                "confidence": "medium", "status": "pending",
                "evidence_summary": "ITER102A1CC evidence"}],
        "custom": [],
    },
    A2: {
        "cqc": [{"regulation_ref": "R10", "regulation_name": "Dignity and respect",
                 "confidence": "low", "status": "rejected",
                 "evidence_summary": "ITER102A2CQCREJ evidence"},
               {"regulation_ref": "R11", "regulation_name": "Need for consent",
                "confidence": "high", "status": "accepted",
                "evidence_summary": "ITER102A2CQC evidence"}],
        "cc": [{"standard_ref": "CC2", "standard_name": "Your personal development",
                "confidence": "high", "status": "accepted",
                "evidence_summary": "ITER102A2CC evidence"}],
        "custom": [{"criterion_ref": "ORG1", "criterion_name": "Local policy",
                    "confidence": "medium", "status": "accepted",
                    "evidence_summary": "ITER102A2CUSTOM evidence"}],
    },
    A3: {
        "cqc": [{"regulation_ref": "R9", "regulation_name": "Person-centred care",
                 "confidence": "medium", "status": "accepted",
                 "evidence_summary": "ITER102A3CQC evidence"}],
        "cc": [{"standard_ref": "CC1", "standard_name": "Understand your role",
                "confidence": "low", "status": "pending",
                "evidence_summary": "ITER102A3CC1 evidence"},
               {"standard_ref": "CC3", "standard_name": "Duty of care",
                "confidence": "high", "status": "accepted",
                "evidence_summary": "ITER102A3CC3 evidence"}],
        "custom": [],
    },
}

TRANSCRIPTS = {
    T1: {"text": "ITER102T1 body mentions Maria Santos here.",
         "speaker_text": "Speaker 1: ITER102T1S Maria Santos spoke."},
    T2: {"text": "ITER102T2 body mentions Maria Santos here.",
         "speaker_text": "Speaker 1: ITER102T2S Maria Santos spoke."},
    T3: {"text": "ITER102T3 body only.",
         "speaker_text": "Speaker 1: ITER102T3S plain."},
}

MEETINGS = [
    # id, title, date, attendees, analysis_id, transcript_id, redactions
    (M1, f"{P}M1 Maria", "2026-06-10T10:00:00+00:00", [MARIA, MANAGER], A1, T1,
     [{"original": "Maria Santos", "replacement": "[Redacted]"}]),
    (M2, f"{P}M2 Diane", "2026-06-11T10:00:00+00:00", [DIANE], A2, T2, []),
    (M3, f"{P}M3 MariaJane", "2026-06-12T10:00:00+00:00", [MARIA, JANE], A3, T3, []),
    (M4, f"{P}M4 Dangling", "2026-06-13T10:00:00+00:00", [JANE], DANGLING_A, DANGLING_T, []),
]


async def seed():
    c = await asyncpg.connect(DSN)
    await cleanup_inner(c)
    for aid, a in ANALYSES.items():
        await c.execute(
            """INSERT INTO analyses (id, meeting_id, org_id, summary, actions, risks,
                   cqc_mappings, care_cert_mappings, custom_mappings, pii_redactions,
                   achievements, learning_needs, created_at)
               VALUES ($1,$2,$3,$4,'[]'::jsonb,'[]'::jsonb,$5::jsonb,$6::jsonb,$7::jsonb,
                       '[]'::jsonb,'[]'::jsonb,'[]'::jsonb,$8)""",
            aid, None, ORG, f"ITER102 summary for {aid}",
            json.dumps(a["cqc"]), json.dumps(a["cc"]), json.dumps(a["custom"]), NOW)
    for tid, t in TRANSCRIPTS.items():
        await c.execute(
            """INSERT INTO transcripts (id, meeting_id, org_id, text, speaker_text, created_at)
               VALUES ($1,$2,$3,$4,$5,$6)""",
            tid, None, ORG, t["text"], t["speaker_text"], NOW)
    for mid, title, date, att, aid, tid, red in MEETINGS:
        await c.execute(
            """INSERT INTO meetings (id, org_id, title, date, status, attendees, analysis_id,
                   transcript_id, created_by, sign_off_manager_id, sign_off_manager_name,
                   pii_redactions, created_at, updated_at)
               VALUES ($1,$2,$3,$4,'signed_off',$5::jsonb,$6,$7,$8,$9,$10,$11::jsonb,$12,$12)""",
            mid, ORG, title, date, json.dumps(att), aid, tid, ADMIN_ID,
            MANAGER["user_id"], MANAGER["name"], json.dumps(red), NOW)
        await c.execute("UPDATE analyses SET meeting_id=$1 WHERE id=$2", mid, aid)
        await c.execute("UPDATE transcripts SET meeting_id=$1 WHERE id=$2", mid, tid)
    for tm, name in ((TEAM_A, f"{P}TeamAlpha"), (TEAM_B, f"{P}TeamBeta")):
        await c.execute(
            "INSERT INTO teams (id, org_id, setting_id, name, members, created_at) VALUES ($1,$2,$3,$4,'[]'::jsonb,$5)",
            tm, ORG, SETTING_ONE, name, NOW)
    # shared_reviewer recipient for the share-meeting tests
    import bcrypt
    pw = bcrypt.hashpw(b"Reviewer123!", bcrypt.gensalt()).decode()
    await c.execute(
        """INSERT INTO users (id, org_id, name, email, role, password_hash, is_active, created_at)
           VALUES ($1,$2,$3,$4,'shared_reviewer',$5,TRUE,$6)""",
        REVIEWER_ID, ORG, f"{P}Reviewer", f"{P}reviewer@example.com", pw, NOW)
    print("seeded ok")
    await c.close()


async def cleanup_inner(c):
    await c.execute("DELETE FROM audit_logs WHERE meeting_id = ANY($1::text[])", [M1, M2, M3, M4])
    await c.execute("DELETE FROM meetings WHERE id = ANY($1::text[])", [M1, M2, M3, M4])
    await c.execute("DELETE FROM analyses WHERE id LIKE $1", P + "%")
    await c.execute("DELETE FROM transcripts WHERE id LIKE $1", P + "%")
    await c.execute("DELETE FROM teams WHERE id LIKE $1", P + "%")
    await c.execute("DELETE FROM users WHERE id LIKE $1", P + "%")
    # restore manager scope in case a dashboard test left it set
    await c.execute("UPDATE users SET setting_id=NULL, team_id=NULL WHERE email='manager@supervision.com'")


async def cleanup():
    c = await asyncpg.connect(DSN)
    await cleanup_inner(c)
    print("cleaned ok")
    await c.close()


if __name__ == "__main__":
    asyncio.run(seed() if sys.argv[1] == "seed" else cleanup())
