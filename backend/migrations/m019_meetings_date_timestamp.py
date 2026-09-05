"""meetings.date TEXT -> TIMESTAMP (no timezone). Deliberately NOT TIMESTAMPTZ:
the column holds a naive local wall-clock value (NewMeeting.js builds it as
"YYYY-MM-DDTHH:MM" from a separate date+time picker, with no timezone
attached), so TIMESTAMPTZ would make Postgres silently reinterpret that local
time as UTC. TIMESTAMP applies no timezone conversion at all, preserving
today's exact semantics. Uses database.py's existing "timestamp" text codec
(already registered for Phase 1 columns) — no new codec needed. Regex is
deliberately more lenient than m005's (which requires full HH:MI:SS) because
live data includes date-only, HH:MM-without-seconds, and full-precision-with-
offset values — verified every current row casts cleanly with this pattern.
"""

VERSION = "019_meetings_date_timestamp"

SQL = """
DO $$
DECLARE
    col_type TEXT;
    bad_count INT;
BEGIN
    SELECT data_type INTO col_type FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'meetings' AND column_name = 'date';
    IF col_type IS NULL OR col_type = 'timestamp without time zone' THEN
        RETURN;
    END IF;
    UPDATE meetings SET date = NULL
        WHERE date IS NOT NULL
        AND date !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T][0-9]{2}:[0-9]{2}(:[0-9]{2}(\\.[0-9]+)?)?([+-][0-9]{2}(:?[0-9]{2})?)?)?$';
    GET DIAGNOSTICS bad_count = ROW_COUNT;
    IF bad_count > 0 THEN
        RAISE WARNING 'meetings.date migration: nulled % malformed value(s)', bad_count;
    END IF;
    BEGIN
        ALTER TABLE meetings ALTER COLUMN date TYPE TIMESTAMP USING date::timestamp;
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'meetings.date migration: could not convert to TIMESTAMP (%) - left as TEXT for manual inspection', SQLERRM;
    END;
END $$;
"""


async def up(conn):
    await conn.execute(SQL)
