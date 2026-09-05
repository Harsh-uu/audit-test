"""Phase 2 date migration: TEXT -> DATE for columns that always hold a plain
YYYY-MM-DD value (no time component, no timezone) — schedules.start_date and
supervision_uploads.meeting_date. Verified clean live data. Requires a matching
DATE text-format codec in database.py (added alongside this migration) so
every existing `date.fromisoformat(...)` / plain-string call site keeps
working unchanged, exactly like the TIMESTAMPTZ codec already does for
Phase 1. Idempotent, same nullify-malformed-then-cast pattern as m005.
"""

VERSION = "018_date_columns_phase2"

SQL = """
DO $$
DECLARE
    migrations TEXT[][] := ARRAY[
        ARRAY['schedules','start_date'],
        ARRAY['supervision_uploads','meeting_date']
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
        IF col_type IS NULL OR col_type = 'date' THEN
            CONTINUE;
        END IF;
        EXECUTE format(
            'UPDATE %I SET %I = NULL WHERE %I IS NOT NULL AND %I !~ %L',
            tbl, col, col, col, '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
        );
        GET DIAGNOSTICS bad_count = ROW_COUNT;
        IF bad_count > 0 THEN
            RAISE WARNING 'Phase-2 date migration: nulled % malformed value(s) in %.%', bad_count, tbl, col;
        END IF;
        BEGIN
            EXECUTE format('ALTER TABLE %I ALTER COLUMN %I TYPE DATE USING %I::date', tbl, col, col);
        EXCEPTION WHEN OTHERS THEN
            RAISE WARNING 'Phase-2 date migration: could not convert %.% to DATE (%) - left as TEXT for manual inspection', tbl, col, SQLERRM;
        END;
    END LOOP;
END $$;
"""


async def up(conn):
    await conn.execute(SQL)
