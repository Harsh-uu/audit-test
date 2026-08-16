-- Supervision2: Organisation RLS Policy Script
-- Run once in Supabase Dashboard > SQL Editor

-- Step 1: Create the limited role
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rls_user') THEN
    CREATE ROLE app_rls_user NOLOGIN;
    RAISE NOTICE 'Created role app_rls_user';
  ELSE
    RAISE NOTICE 'Role app_rls_user already exists - skipping CREATE';
  END IF;
END $$;

-- Step 2: Grant privileges
GRANT USAGE ON SCHEMA public TO app_rls_user;

GRANT SELECT, INSERT, UPDATE, DELETE ON
    meetings, transcripts, analyses, audio_files, review_edits,
    reviewer_comments, standards_entries, standards_documents,
    audit_logs, org_settings, teams, schedules, meeting_types,
    meeting_prep, focus_topics, supervision_uploads,
    users, organisations, invitations, settings, jobs,
    refresh_tokens, login_attempts, password_reset_tokens
TO app_rls_user;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rls_user;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rls_user;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_rls_user;

-- Step 3: Enable RLS and create policies on all tenant tables

ALTER TABLE meetings ENABLE ROW LEVEL SECURITY;
ALTER TABLE meetings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS meetings_rls ON meetings;
CREATE POLICY meetings_rls ON meetings FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

ALTER TABLE transcripts ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcripts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS transcripts_rls ON transcripts;
CREATE POLICY transcripts_rls ON transcripts FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

ALTER TABLE analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyses FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS analyses_rls ON analyses;
CREATE POLICY analyses_rls ON analyses FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

ALTER TABLE audio_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE audio_files FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audio_files_rls ON audio_files;
CREATE POLICY audio_files_rls ON audio_files FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

ALTER TABLE review_edits ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_edits FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS review_edits_rls ON review_edits;
CREATE POLICY review_edits_rls ON review_edits FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

ALTER TABLE reviewer_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE reviewer_comments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS reviewer_comments_rls ON reviewer_comments;
CREATE POLICY reviewer_comments_rls ON reviewer_comments FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

ALTER TABLE standards_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE standards_documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS standards_documents_rls ON standards_documents;
CREATE POLICY standards_documents_rls ON standards_documents FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audit_logs_rls ON audit_logs;
CREATE POLICY audit_logs_rls ON audit_logs FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

ALTER TABLE org_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_settings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_settings_rls ON org_settings;
CREATE POLICY org_settings_rls ON org_settings FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE teams FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS teams_rls ON teams;
CREATE POLICY teams_rls ON teams FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

ALTER TABLE schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE schedules FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS schedules_rls ON schedules;
CREATE POLICY schedules_rls ON schedules FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

ALTER TABLE meeting_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_types FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS meeting_types_rls ON meeting_types;
CREATE POLICY meeting_types_rls ON meeting_types FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

ALTER TABLE meeting_prep ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_prep FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS meeting_prep_rls ON meeting_prep;
CREATE POLICY meeting_prep_rls ON meeting_prep FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

ALTER TABLE focus_topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE focus_topics FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS focus_topics_rls ON focus_topics;
CREATE POLICY focus_topics_rls ON focus_topics FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

ALTER TABLE supervision_uploads ENABLE ROW LEVEL SECURITY;
ALTER TABLE supervision_uploads FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS supervision_uploads_rls ON supervision_uploads;
CREATE POLICY supervision_uploads_rls ON supervision_uploads FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

-- Step 4: users table (was missing RLS entirely)
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS users_rls ON users;
CREATE POLICY users_rls ON users FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

-- Step 5: standards_entries dual policy
-- System CQC/Care Certificate records have org_id IS NULL and are visible to all orgs.
-- Custom org standards are scoped to the owning org only.
ALTER TABLE standards_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE standards_entries FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS standards_entries_rls ON standards_entries;
CREATE POLICY standards_entries_rls ON standards_entries FOR ALL
    USING (
        org_id IS NULL
        OR org_id = current_setting('app.current_org_id', TRUE)
    )
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

-- ── Phase 2: Tables flagged by Security Advisor (added Aug 2026) ─────────────

-- evidence_feedback
ALTER TABLE evidence_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_feedback FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS evidence_feedback_rls ON evidence_feedback;
CREATE POLICY evidence_feedback_rls ON evidence_feedback FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

-- invitations
ALTER TABLE invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE invitations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS invitations_rls ON invitations;
CREATE POLICY invitations_rls ON invitations FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

-- settings
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS settings_rls ON settings;
CREATE POLICY settings_rls ON settings FOR ALL
    USING      (org_id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (org_id = current_setting('app.current_org_id', TRUE));

-- organisations (its own id IS the org boundary)
ALTER TABLE organisations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organisations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS organisations_rls ON organisations;
CREATE POLICY organisations_rls ON organisations FOR ALL
    USING      (id = current_setting('app.current_org_id', TRUE))
    WITH CHECK (id = current_setting('app.current_org_id', TRUE));

-- jobs (no org_id — background worker only; admin-only access)
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS jobs_rls ON jobs;
CREATE POLICY jobs_rls ON jobs FOR ALL USING (FALSE);

-- login_attempts (no org_id — auth brute-force tracking only; admin-only)
ALTER TABLE login_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE login_attempts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS login_attempts_rls ON login_attempts;
CREATE POLICY login_attempts_rls ON login_attempts FOR ALL USING (FALSE);

-- password_reset_tokens (no org_id — auth flow only; admin-only)
ALTER TABLE password_reset_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE password_reset_tokens FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS password_reset_tokens_rls ON password_reset_tokens;
CREATE POLICY password_reset_tokens_rls ON password_reset_tokens FOR ALL USING (FALSE);

-- refresh_tokens (token security — admin connection only)
ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE refresh_tokens FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS refresh_tokens_rls ON refresh_tokens;
CREATE POLICY refresh_tokens_rls ON refresh_tokens FOR ALL USING (FALSE);

-- Verification: should show 25 rows all with rls_enabled=true and policy_count=1
SELECT
    tablename,
    rowsecurity AS rls_enabled,
    (SELECT COUNT(*) FROM pg_policies p
     WHERE p.schemaname = t.schemaname AND p.tablename = t.tablename) AS policy_count
FROM pg_tables t
WHERE schemaname = 'public'
  AND tablename IN (
      'meetings','transcripts','analyses','audio_files','review_edits',
      'reviewer_comments','standards_entries','standards_documents',
      'audit_logs','org_settings','teams','schedules','meeting_types',
      'meeting_prep','focus_topics','supervision_uploads','users'
  )
ORDER BY tablename;
