"""Phase 1 follow-up: focus_topics.created_at was missed from m005's TEXT ->
TIMESTAMPTZ list. Its insert already uses datetime.now(timezone.utc).isoformat()
— the identical pattern as every other column m005 converted — so this is a
plain oversight, not a deliberate exclusion. Same idempotent approach as m005.
"""

VERSION = "016_focus_topics_created_at"

SQL = """
DO $$
DECLARE
    col_type TEXT;
    bad_count INT;
BEGIN
    SELECT data_type INTO col_type FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'focus_topics' AND column_name = 'created_at';
    IF col_type IS NULL OR col_type = 'timestamp with time zone' THEN
        RETURN;
    END IF;
    UPDATE focus_topics SET created_at = NULL
        WHERE created_at IS NOT NULL AND created_at !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}';
    GET DIAGNOSTICS bad_count = ROW_COUNT;
    IF bad_count > 0 THEN
        RAISE WARNING 'focus_topics.created_at migration: nulled % malformed value(s)', bad_count;
    END IF;
    BEGIN
        ALTER TABLE focus_topics ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at::timestamptz;
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'focus_topics.created_at migration: could not convert (%) - left as TEXT', SQLERRM;
    END;
END $$;
"""


async def up(conn):
    await conn.execute(SQL)
