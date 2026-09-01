"""Foreign key constraints linking meetings/users/orgs, plus their supporting indexes."""

VERSION = "004_fk_constraints"

SQL = """
-- ── Foreign key constraints ─────────────────────────────────────────────────────
-- The schema previously had zero formal relationships — every "belongs to" link
-- (transcript->meeting, team->org, user->team, etc.) was only ever enforced by
-- application code. That's the root cause of orphaned rows appearing over time
-- (e.g. audit_logs entries outliving their meeting). These constraints make
-- Postgres enforce the same relationships the app already assumes, matching the
-- app's existing manual-cascade/unassign behavior exactly:
--   • CASCADE on org_id / meeting_id chains — app already bulk-deletes these
--     children when the meeting/org is deleted (meetings.py delete_meeting()).
--   • SET NULL on soft/ownership references (team_id, setting_id, supervisor,
--     manager) — app already manually nulls these out when the parent is
--     deleted (org.py delete_team()/delete_setting()).
-- Postgres doesn't support "ADD CONSTRAINT IF NOT EXISTS", so each is wrapped in
-- a DO block that swallows the "already exists" error, matching the idempotent
-- pattern used for app_rls_user above.
--
-- Deliberately NOT added (documented, not oversights):
--   • jobs.meeting_id — app intentionally keeps job history after a meeting is
--     deleted (not in delete_meeting()'s cascade list); adding a FK here would
--     change that behavior. Also has 1 pre-existing orphan row.
--   • invitations.user_id — has 1 pre-existing orphan row; needs a product
--     decision on cleanup before it can be constrained.
--   • meetings.transcript_id / analysis_id / audio_file_id — these are the
--     reverse/denormalized pointers of transcripts.meeting_id etc. (already
--     covered in the correct "child belongs to parent" direction below);
--     constraining both directions risks a circular-FK insert-order issue.
--   • meetings.created_by / sign_off_manager_id — intentional historical
--     snapshots (created_by_name / sign_off_manager_name persist even after the
--     referenced user account is deleted); sign_off_manager_id already has 4
--     such orphans today, confirming this is by design, not a bug.

-- One-time cleanup: 3 audit_logs rows already outlived their meeting (the exact
-- symptom described above) — finish the cascade delete that should have already
-- happened, so the new CASCADE constraint below can be added.
DELETE FROM audit_logs WHERE meeting_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM meetings m WHERE m.id = audit_logs.meeting_id);

DO $$ BEGIN ALTER TABLE users ADD CONSTRAINT fk_users_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE users ADD CONSTRAINT fk_users_team_id FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE users ADD CONSTRAINT fk_users_setting_id FOREIGN KEY (setting_id) REFERENCES org_settings(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE meetings ADD CONSTRAINT fk_meetings_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE meetings ADD CONSTRAINT fk_meetings_team_id FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE meetings ADD CONSTRAINT fk_meetings_setting_id FOREIGN KEY (setting_id) REFERENCES org_settings(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE meetings ADD CONSTRAINT fk_meetings_schedule_id FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE transcripts ADD CONSTRAINT fk_transcripts_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE transcripts ADD CONSTRAINT fk_transcripts_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE analyses ADD CONSTRAINT fk_analyses_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE analyses ADD CONSTRAINT fk_analyses_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE audio_files ADD CONSTRAINT fk_audio_files_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE audio_files ADD CONSTRAINT fk_audio_files_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE review_edits ADD CONSTRAINT fk_review_edits_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE review_edits ADD CONSTRAINT fk_review_edits_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE reviewer_comments ADD CONSTRAINT fk_reviewer_comments_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE reviewer_comments ADD CONSTRAINT fk_reviewer_comments_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE audit_logs ADD CONSTRAINT fk_audit_logs_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE audit_logs ADD CONSTRAINT fk_audit_logs_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE org_settings ADD CONSTRAINT fk_org_settings_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE org_settings ADD CONSTRAINT fk_org_settings_manager_user_id FOREIGN KEY (manager_user_id) REFERENCES users(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE teams ADD CONSTRAINT fk_teams_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE teams ADD CONSTRAINT fk_teams_setting_id FOREIGN KEY (setting_id) REFERENCES org_settings(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE teams ADD CONSTRAINT fk_teams_supervisor_user_id FOREIGN KEY (supervisor_user_id) REFERENCES users(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE standards_entries ADD CONSTRAINT fk_standards_entries_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE standards_documents ADD CONSTRAINT fk_standards_documents_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE invitations ADD CONSTRAINT fk_invitations_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
-- NOTE: no FK from settings.org_id -> organisations(id): settings.org_id is
-- deliberately kept TEXT forever (see m006_phase2_uuid.py — settings.id
-- is a composite string key, not a real relational row), so it can never
-- have a type-matching FK to organisations(id), which is UUID.
DO $$ BEGIN ALTER TABLE meeting_types ADD CONSTRAINT fk_meeting_types_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE focus_topics ADD CONSTRAINT fk_focus_topics_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE meeting_prep ADD CONSTRAINT fk_meeting_prep_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE meeting_prep ADD CONSTRAINT fk_meeting_prep_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE schedules ADD CONSTRAINT fk_schedules_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE schedules ADD CONSTRAINT fk_schedules_staff_user_id FOREIGN KEY (staff_user_id) REFERENCES users(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE schedules ADD CONSTRAINT fk_schedules_meeting_type_id FOREIGN KEY (meeting_type_id) REFERENCES meeting_types(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE supervision_uploads ADD CONSTRAINT fk_supervision_uploads_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE supervision_uploads ADD CONSTRAINT fk_supervision_uploads_staff_id FOREIGN KEY (staff_id) REFERENCES users(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

DO $$ BEGIN ALTER TABLE evidence_feedback ADD CONSTRAINT fk_evidence_feedback_meeting_id FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;
DO $$ BEGIN ALTER TABLE evidence_feedback ADD CONSTRAINT fk_evidence_feedback_org_id FOREIGN KEY (org_id) REFERENCES organisations(id) ON DELETE CASCADE; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; END $$;

-- ── FK-supporting indexes ────────────────────────────────────────────────────
-- Every FK column above needs a supporting index so that deleting/updating the
-- REFERENCED row (e.g. deleting an org, a user, a meeting) doesn't force a full
-- table scan of the referencing table to find rows to CASCADE/SET NULL. This is
-- a distinct concern from the composite query-pattern indexes elsewhere in this
-- file (e.g. idx_meetings_org_status_date already covers meetings.org_id for
-- SELECT filtering) — some FK columns had no index at all for either purpose.
CREATE INDEX IF NOT EXISTS idx_analyses_org_id ON analyses(org_id);
CREATE INDEX IF NOT EXISTS idx_audio_files_org_id ON audio_files(org_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_org_id ON audit_logs(org_id);
CREATE INDEX IF NOT EXISTS idx_evidence_feedback_org_id ON evidence_feedback(org_id);
CREATE INDEX IF NOT EXISTS idx_evidence_feedback_meeting_id ON evidence_feedback(meeting_id);
CREATE INDEX IF NOT EXISTS idx_invitations_org_id ON invitations(org_id);
CREATE INDEX IF NOT EXISTS idx_meeting_prep_org_id ON meeting_prep(org_id);
CREATE INDEX IF NOT EXISTS idx_meetings_setting_id ON meetings(setting_id);
CREATE INDEX IF NOT EXISTS idx_meetings_team_id ON meetings(team_id);
CREATE INDEX IF NOT EXISTS idx_meetings_schedule_id ON meetings(schedule_id);
CREATE INDEX IF NOT EXISTS idx_org_settings_manager_user_id ON org_settings(manager_user_id);
CREATE INDEX IF NOT EXISTS idx_review_edits_org_id ON review_edits(org_id);
CREATE INDEX IF NOT EXISTS idx_reviewer_comments_org_id ON reviewer_comments(org_id);
CREATE INDEX IF NOT EXISTS idx_schedules_meeting_type_id ON schedules(meeting_type_id);
CREATE INDEX IF NOT EXISTS idx_schedules_staff_user_id ON schedules(staff_user_id);
CREATE INDEX IF NOT EXISTS idx_standards_entries_org_id ON standards_entries(org_id);
CREATE INDEX IF NOT EXISTS idx_teams_supervisor_user_id ON teams(supervisor_user_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_org_id ON transcripts(org_id);
"""


async def up(conn):
    await conn.execute(SQL)
