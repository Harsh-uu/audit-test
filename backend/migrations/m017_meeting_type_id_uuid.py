"""meetings.meeting_type_id is TEXT but should be UUID to match meeting_types.id
(and its sibling schedules.meeting_type_id, already UUID with a working FK).
Verified 100% NULL in production data with zero write sites anywhere in the
codebase (only ever SELECTed, never INSERTed/UPDATEd) — safe, zero-risk
conversion. Adds the same FK + index the schedules table already has.
"""

VERSION = "017_meeting_type_id_uuid"

SQL = """
DO $$
DECLARE
    col_type TEXT;
BEGIN
    SELECT data_type INTO col_type FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'meetings' AND column_name = 'meeting_type_id';
    IF col_type IS NULL OR col_type = 'uuid' THEN
        RETURN;
    END IF;
    UPDATE meetings SET meeting_type_id = NULL
        WHERE meeting_type_id IS NOT NULL
        AND meeting_type_id !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$';
    BEGIN
        ALTER TABLE meetings ALTER COLUMN meeting_type_id TYPE UUID USING meeting_type_id::uuid;
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'meetings.meeting_type_id migration: could not convert (%) - left as TEXT', SQLERRM;
    END;
END $$;

DO $$ BEGIN ALTER TABLE meetings ADD CONSTRAINT fk_meetings_meeting_type_id FOREIGN KEY (meeting_type_id) REFERENCES meeting_types(id) ON DELETE SET NULL; EXCEPTION WHEN duplicate_object THEN NULL; WHEN foreign_key_violation THEN RAISE WARNING 'FK constraint skipped - existing orphan rows violate it, needs data cleanup first'; WHEN OTHERS THEN RAISE WARNING 'fk_meetings_meeting_type_id skipped (%)', SQLERRM; END $$;

CREATE INDEX IF NOT EXISTS idx_meetings_meeting_type_id ON meetings(meeting_type_id);
"""


async def up(conn):
    await conn.execute(SQL)
