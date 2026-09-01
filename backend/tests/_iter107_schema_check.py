"""Verify all 52 Phase-1 columns are timestamptz + row counts vs backup."""
import asyncio, json, sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
import database

COLS = [
 ('organisations','created_at'),('organisations','updated_at'),
 ('users','password_changed_at'),('users','created_at'),('users','updated_at'),('users','mfa_code_expires_at'),
 ('meetings','recording_notice_shown_at'),('meetings','audio_grace_period_started_at'),('meetings','audio_deleted_at'),
 ('meetings','retranscribed_at'),('meetings','created_at'),('meetings','updated_at'),
 ('meetings','pii_reviewed_at'),('meetings','reopen_requested_at'),('meetings','reopen_approved_at'),
 ('transcripts','retranscribed_at'),('transcripts','created_at'),('transcripts','updated_at'),
 ('transcripts','speaker_text_backup_at'),('transcripts','speaker_text_edited_at'),
 ('analyses','created_at'),('analyses','last_edited_at'),('analyses','rescanned_at'),
 ('audio_files','deleted_at'),('audio_files','created_at'),
 ('review_edits','timestamp'),('reviewer_comments','created_at'),
 ('standards_entries','created_at'),('standards_documents','parsed_at'),('standards_documents','created_at'),
 ('login_attempts','locked_until'),('login_attempts','updated_at'),
 ('password_reset_tokens','expires_at'),
 ('invitations','expires_at'),('invitations','used_at'),('invitations','created_at'),
 ('jobs','created_at'),('jobs','updated_at'),('audit_logs','timestamp'),
 ('org_settings','created_at'),('org_settings','updated_at'),
 ('teams','created_at'),('schedules','created_at'),('meeting_types','created_at'),
 ('meeting_prep','generated_at'),('meeting_prep','coverage_checked_at'),('meeting_prep','shared_at'),
 ('meeting_prep','created_at'),('meeting_prep','updated_at'),
 ('supervision_uploads','processed_at'),('supervision_uploads','created_at'),
 ('evidence_feedback','timestamp'),
]


async def main():
    await database.create_pool()
    bad = []
    async with database.with_admin() as conn:
        for t, c in COLS:
            dt = await conn.fetchval(
                "SELECT data_type FROM information_schema.columns WHERE table_schema='public' AND table_name=$1 AND column_name=$2", t, c)
            if dt != 'timestamp with time zone':
                bad.append((t, c, dt))
        print(f"checked {len(COLS)} columns; NOT timestamptz: {bad}")
        # row counts vs backup
        backup = json.load(open('/app/backups/pre_phase1_timestamptz_backup.json'))
        tables = backup.keys() if isinstance(backup, dict) else []
        diffs = []
        for t in tables:
            rows = backup[t]
            if not isinstance(rows, list):
                continue
            n = await conn.fetchval(f"SELECT count(*) FROM {t}")
            if n != len(rows):
                diffs.append((t, len(rows), n))
        print("row-count diffs (table, backup, now):", diffs)
        # null audit for previously non-null values
        nulls = []
        for t in tables:
            rows = backup[t] if isinstance(backup[t], list) else []
            if not rows:
                continue
            for tt, c in COLS:
                if tt != t:
                    continue
                had = sum(1 for r in rows if r.get(c))
                now_n = await conn.fetchval(f'SELECT count({c}) FROM {t}')
                if now_n < had:
                    nulls.append((t, c, had, now_n))
        print("columns that LOST non-null values:", nulls)
    await database.close_pool()

asyncio.run(main())
