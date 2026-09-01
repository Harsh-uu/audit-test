"""Phase 2 data-type migration: TEXT -> UUID for id / foreign-key columns."""

VERSION = "006_phase2_uuid"

SQL = """
-- Every id/foreign-key column that always holds an app-generated UUID
-- (str(uuid.uuid4()) or gen_random_uuid()) is converted from TEXT to native
-- UUID. database.py registers a text-format UUID codec (_encode_uuid/_decode_uuid)
-- so every existing string-based id comparison / f-string / JSON payload is
-- completely unaffected — this is the same technique used for the Phase 1
-- TIMESTAMPTZ migration (m005_phase1_timestamptz.py).
-- Deliberately EXCLUDED (kept TEXT — confirmed NOT uuid-shaped by inspecting
-- both the generating code and the live data before writing this migration):
--   • login_attempts.identifier — composite string ("login_ip:1.2.3.4", "create_meeting:<uid>", email, etc.)
--   • password_reset_tokens.token / invitations.token — secrets.token_urlsafe(32)
--   • evidence_feedback.evidence_item_id — str(uuid.uuid4())[:8], truncated to 8 chars, not a full UUID
--   • settings.id / settings.org_id — settings.id is a COMPOSITE STRING key
--     ("supervision_template:{org_id}", or the bare literal "supervision_template")
--     used by admin.py get_template/save_template, review.py and
--     transcription_pipeline.py — not a UUID at all, and org_id on that same
--     table can be '' (falsy org_id fallback), not just NULL/uuid.
--   • meetings.date / schedules.start_date / supervision_uploads.meeting_date / focus_topics.active_month
--     — unrelated date-only fields already excluded from Phase 1 above, not id columns anyway.
-- This is ONE all-or-nothing block: RLS policies (which Postgres refuses to let
-- you change a column's type underneath) and every FK constraint are dropped
-- first, columns are converted, then both are rebuilt from what was captured/
-- known before the drop. If ANYTHING fails partway, the whole block rolls back
-- automatically (a DO block is an implicit subtransaction) — the schema, its
-- FKs and its RLS policies all revert to exactly what they were, safe to retry
-- on the next restart once whatever caused the failure is fixed.
DO $$
DECLARE
    id_columns TEXT[][] := ARRAY[
        ARRAY['organisations','id'],
        ARRAY['users','id'], ARRAY['users','org_id'], ARRAY['users','team_id'], ARRAY['users','setting_id'],
        ARRAY['meetings','id'], ARRAY['meetings','org_id'], ARRAY['meetings','team_id'], ARRAY['meetings','setting_id'],
        ARRAY['meetings','schedule_id'], ARRAY['meetings','created_by'], ARRAY['meetings','sign_off_manager_id'],
        ARRAY['meetings','audio_file_id'], ARRAY['meetings','transcript_id'], ARRAY['meetings','analysis_id'],
        ARRAY['transcripts','id'], ARRAY['transcripts','meeting_id'], ARRAY['transcripts','org_id'],
        ARRAY['analyses','id'], ARRAY['analyses','meeting_id'], ARRAY['analyses','org_id'],
        ARRAY['audio_files','id'], ARRAY['audio_files','meeting_id'], ARRAY['audio_files','org_id'],
        ARRAY['review_edits','id'], ARRAY['review_edits','meeting_id'], ARRAY['review_edits','org_id'], ARRAY['review_edits','user_id'],
        ARRAY['reviewer_comments','id'], ARRAY['reviewer_comments','meeting_id'], ARRAY['reviewer_comments','org_id'], ARRAY['reviewer_comments','user_id'],
        ARRAY['standards_entries','id'], ARRAY['standards_entries','org_id'], ARRAY['standards_entries','created_by'],
        ARRAY['standards_documents','id'], ARRAY['standards_documents','org_id'], ARRAY['standards_documents','uploaded_by'],
        ARRAY['invitations','id'], ARRAY['invitations','org_id'], ARRAY['invitations','user_id'],
        ARRAY['audit_logs','id'], ARRAY['audit_logs','meeting_id'], ARRAY['audit_logs','org_id'], ARRAY['audit_logs','user_id'],
        ARRAY['org_settings','id'], ARRAY['org_settings','org_id'], ARRAY['org_settings','manager_user_id'],
        ARRAY['teams','id'], ARRAY['teams','org_id'], ARRAY['teams','setting_id'], ARRAY['teams','supervisor_user_id'],
        ARRAY['schedules','id'], ARRAY['schedules','org_id'], ARRAY['schedules','staff_user_id'], ARRAY['schedules','meeting_type_id'], ARRAY['schedules','created_by'],
        ARRAY['meeting_types','id'], ARRAY['meeting_types','org_id'],
        ARRAY['meeting_prep','id'], ARRAY['meeting_prep','meeting_id'], ARRAY['meeting_prep','org_id'], ARRAY['meeting_prep','created_by'],
        ARRAY['focus_topics','id'], ARRAY['focus_topics','org_id'], ARRAY['focus_topics','created_by'],
        ARRAY['supervision_uploads','id'], ARRAY['supervision_uploads','org_id'], ARRAY['supervision_uploads','staff_id'], ARRAY['supervision_uploads','uploader_id'],
        ARRAY['evidence_feedback','id'], ARRAY['evidence_feedback','meeting_id'], ARRAY['evidence_feedback','org_id'], ARRAY['evidence_feedback','user_id'],
        ARRAY['password_reset_tokens','id'],
        ARRAY['jobs','id'], ARRAY['jobs','meeting_id']
    ];
    org_policies TEXT[][] := ARRAY[
        ARRAY['organisations','organisations_rls','id'],
        ARRAY['users','users_rls','org_id'], ARRAY['meetings','meetings_rls','org_id'],
        ARRAY['transcripts','transcripts_rls','org_id'], ARRAY['analyses','analyses_rls','org_id'],
        ARRAY['audio_files','audio_files_rls','org_id'], ARRAY['review_edits','review_edits_rls','org_id'],
        ARRAY['reviewer_comments','reviewer_comments_rls','org_id'], ARRAY['standards_documents','standards_documents_rls','org_id'],
        ARRAY['invitations','invitations_rls','org_id'],
        ARRAY['audit_logs','audit_logs_rls','org_id'], ARRAY['org_settings','org_settings_rls','org_id'],
        ARRAY['teams','teams_rls','org_id'], ARRAY['schedules','schedules_rls','org_id'],
        ARRAY['meeting_types','meeting_types_rls','org_id'], ARRAY['meeting_prep','meeting_prep_rls','org_id'],
        ARRAY['focus_topics','focus_topics_rls','org_id'], ARRAY['supervision_uploads','supervision_uploads_rls','org_id'],
        ARRAY['evidence_feedback','evidence_feedback_rls','org_id']
    ];
    m TEXT[];
    tbl TEXT;
    col TEXT;
    pol TEXT;
    col_type TEXT;
    not_null BOOLEAN;
    bad_count INT;
    fk RECORD;
    already_uuid BOOLEAN;
    cast_expr TEXT := 'NULLIF((SELECT current_setting(''app.current_org_id'', TRUE)), '''')::uuid';
BEGIN
    -- Idempotent short-circuit: if organisations.id is already uuid, a prior
    -- run already fully committed this migration (all-or-nothing, so every
    -- other column/FK/policy is guaranteed to be uuid-aware too) — skip.
    SELECT (data_type = 'uuid') INTO already_uuid FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'organisations' AND column_name = 'id';
    IF already_uuid THEN
        RETURN;
    END IF;

    -- 1. Capture every existing FK constraint's exact definition, then drop
    --    them all (Postgres refuses to change a column's type while a FK
    --    with a different type still references/uses it).
    CREATE TEMP TABLE IF NOT EXISTS _phase2_fk_backup (conname text, tbl text, def text);
    DELETE FROM _phase2_fk_backup;
    INSERT INTO _phase2_fk_backup
        SELECT conname, conrelid::regclass::text, pg_get_constraintdef(oid)
        FROM pg_constraint WHERE contype = 'f' AND connamespace = 'public'::regnamespace;
    FOR fk IN SELECT * FROM _phase2_fk_backup LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', fk.tbl, fk.conname);
    END LOOP;

    -- 2. Drop the 21 RLS policies (must happen before ALTER COLUMN TYPE —
    --    Postgres refuses to change the type of a column a policy depends on).
    FOREACH m SLICE 1 IN ARRAY org_policies LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I ON %I', m[2], m[1]);
    END LOOP;
    EXECUTE 'DROP POLICY IF EXISTS standards_entries_rls ON standards_entries';

    -- 3. password_reset_tokens.id has a TEXT-cast default that can't be
    --    auto-cast to uuid; drop it before the type conversion, then set the
    --    native equivalent back afterwards (step 6).
    ALTER TABLE password_reset_tokens ALTER COLUMN id DROP DEFAULT;

    -- 4. Convert every id/FK column. Non-UUID values (only ever seen on
    --    nullable historical-snapshot columns — e.g. 4 pre-existing ''
    --    rows in meetings.sign_off_manager_id) are nulled first, logged via
    --    RAISE WARNING, so the ALTER can succeed. If the column is NOT NULL
    --    (i.e. a primary/composite key — e.g. settings.id, which is why that
    --    table is excluded above), silently nulling it would just hit a
    --    confusing NOT NULL violation a moment later — instead we RAISE
    --    EXCEPTION with a clear message so it's obvious the column was
    --    wrongly added to id_columns, caught by the outer EXCEPTION below.
    FOREACH m SLICE 1 IN ARRAY id_columns LOOP
        tbl := m[1];
        col := m[2];
        SELECT data_type, (is_nullable = 'NO') INTO col_type, not_null FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = tbl AND column_name = col;
        IF col_type IS NULL OR col_type = 'uuid' THEN
            CONTINUE;
        END IF;
        EXECUTE format(
            'SELECT count(*) FROM %I WHERE %I IS NOT NULL AND %I !~ %L',
            tbl, col, col, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        ) INTO bad_count;
        IF bad_count > 0 AND not_null THEN
            RAISE EXCEPTION 'Phase-2 migration: %.% is NOT NULL and has % non-UUID value(s) — this column is not uuid-shaped and must not be in id_columns', tbl, col, bad_count;
        ELSIF bad_count > 0 THEN
            EXECUTE format(
                'UPDATE %I SET %I = NULL WHERE %I IS NOT NULL AND %I !~ %L',
                tbl, col, col, col, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
            );
            RAISE WARNING 'Phase-2 migration: nulled % non-UUID value(s) in %.% before UUID conversion', bad_count, tbl, col;
        END IF;
        EXECUTE format('ALTER TABLE %I ALTER COLUMN %I TYPE UUID USING %I::uuid', tbl, col, col);
    END LOOP;

    -- 5. Re-add every FK exactly as captured (types now match on both sides).
    FOR fk IN SELECT * FROM _phase2_fk_backup LOOP
        EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s', fk.tbl, fk.conname, fk.def);
    END LOOP;

    -- 6. Recreate the 21 RLS policies, now uuid-aware. NULLIF(...,'') guards
    --    the empty-string default app.current_org_id gets when unset —
    --    casting NULL to uuid is always NULL (never errors), so it just
    --    fails closed (matches TEXT-era behavior of comparing against '').
    FOREACH m SLICE 1 IN ARRAY org_policies LOOP
        tbl := m[1]; pol := m[2]; col := m[3];
        EXECUTE format('CREATE POLICY %I ON %I FOR ALL USING (%I = %s) WITH CHECK (%I = %s)',
            pol, tbl, col, cast_expr, col, cast_expr);
    END LOOP;
    EXECUTE format(
        'CREATE POLICY standards_entries_rls ON standards_entries FOR ALL USING (org_id IS NULL OR org_id = %s) WITH CHECK (org_id = %s)',
        cast_expr, cast_expr
    );

    -- 7. Native uuid default (previously cast through TEXT because the
    --    column itself was TEXT).
    ALTER TABLE password_reset_tokens ALTER COLUMN id SET DEFAULT gen_random_uuid();

    RAISE NOTICE 'Phase-2 migration: all id/FK columns converted TEXT -> UUID successfully';
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'Phase-2 UUID migration failed and was fully rolled back (schema unchanged): %', SQLERRM;
END $$;
"""


async def up(conn):
    await conn.execute(SQL)
