"""Phase 1 data-type migration: TEXT -> TIMESTAMPTZ for true date/time columns."""

VERSION = "005_phase1_timestamptz"

SQL = """
-- Scoped to the columns that always hold a full ISO-8601 UTC timestamp written via
-- datetime.now(timezone.utc).isoformat() (database.py registers a text-format
-- TIMESTAMPTZ/TIMESTAMP codec so those call sites keep working unchanged — see
-- _encode_timestamp/_decode_timestamp). Deliberately EXCLUDED, left as TEXT
-- (different semantics, not full timestamps): meetings.date (plain user-supplied
-- date), schedules.start_date (code comment already says "keep as str — DB column
-- is text"), supervision_uploads.meeting_date (date-only), focus_topics.
-- active_month ("YYYY-MM" only).
-- Idempotent: skips columns that are already TIMESTAMPTZ or don't exist (safe on
-- a fresh DB or one already migrated). Malformed values (don't look like
-- YYYY-MM-DD[ T]HH:MI:SS) are nulled out first — logged via RAISE WARNING — so the
-- ALTER can succeed; if a column still can't be cast for any other reason it's
-- left as TEXT with a loud warning for manual inspection rather than aborting the
-- whole migration.
DO $$
DECLARE
    migrations TEXT[][] := ARRAY[
        ARRAY['organisations','created_at'], ARRAY['organisations','updated_at'],
        ARRAY['users','password_changed_at'], ARRAY['users','created_at'], ARRAY['users','updated_at'], ARRAY['users','mfa_code_expires_at'],
        ARRAY['meetings','recording_notice_shown_at'], ARRAY['meetings','audio_grace_period_started_at'], ARRAY['meetings','audio_deleted_at'],
        ARRAY['meetings','retranscribed_at'], ARRAY['meetings','created_at'], ARRAY['meetings','updated_at'],
        ARRAY['meetings','pii_reviewed_at'], ARRAY['meetings','reopen_requested_at'], ARRAY['meetings','reopen_approved_at'],
        ARRAY['transcripts','retranscribed_at'], ARRAY['transcripts','created_at'], ARRAY['transcripts','updated_at'],
        ARRAY['transcripts','speaker_text_backup_at'], ARRAY['transcripts','speaker_text_edited_at'],
        ARRAY['analyses','created_at'], ARRAY['analyses','last_edited_at'], ARRAY['analyses','rescanned_at'],
        ARRAY['audio_files','deleted_at'], ARRAY['audio_files','created_at'],
        ARRAY['review_edits','timestamp'], ARRAY['reviewer_comments','created_at'],
        ARRAY['standards_entries','created_at'], ARRAY['standards_documents','parsed_at'], ARRAY['standards_documents','created_at'],
        ARRAY['login_attempts','locked_until'], ARRAY['login_attempts','updated_at'],
        ARRAY['password_reset_tokens','expires_at'],
        ARRAY['invitations','expires_at'], ARRAY['invitations','used_at'], ARRAY['invitations','created_at'],
        ARRAY['jobs','created_at'], ARRAY['jobs','updated_at'],
        ARRAY['audit_logs','timestamp'],
        ARRAY['org_settings','created_at'], ARRAY['org_settings','updated_at'],
        ARRAY['teams','created_at'], ARRAY['schedules','created_at'], ARRAY['meeting_types','created_at'],
        ARRAY['meeting_prep','generated_at'], ARRAY['meeting_prep','coverage_checked_at'], ARRAY['meeting_prep','shared_at'],
        ARRAY['meeting_prep','created_at'], ARRAY['meeting_prep','updated_at'],
        ARRAY['supervision_uploads','processed_at'], ARRAY['supervision_uploads','created_at'],
        ARRAY['evidence_feedback','timestamp']
    ];
    m TEXT[];
    tbl TEXT;
    col TEXT;
    col_type TEXT;
    bad_count INT;
BEGIN
    FOREACH m SLICE 1 IN ARRAY migrations LOOP
        tbl := m[1];
        col := m[2];
        SELECT data_type INTO col_type FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = tbl AND column_name = col;
        IF col_type IS NULL OR col_type = 'timestamp with time zone' THEN
            CONTINUE;
        END IF;
        EXECUTE format(
            'UPDATE %I SET %I = NULL WHERE %I IS NOT NULL AND %I !~ %L',
            tbl, col, col, col, '^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}'
        );
        GET DIAGNOSTICS bad_count = ROW_COUNT;
        IF bad_count > 0 THEN
            RAISE WARNING 'Phase-1 migration: nulled % malformed value(s) in %.% before TIMESTAMPTZ conversion', bad_count, tbl, col;
        END IF;
        BEGIN
            EXECUTE format('ALTER TABLE %I ALTER COLUMN %I TYPE TIMESTAMPTZ USING %I::timestamptz', tbl, col, col);
        EXCEPTION WHEN OTHERS THEN
            RAISE WARNING 'Phase-1 migration: could not convert %.% to TIMESTAMPTZ (%) - left as TEXT for manual inspection', tbl, col, SQLERRM;
        END;
    END LOOP;
END $$;
"""


async def up(conn):
    await conn.execute(SQL)
