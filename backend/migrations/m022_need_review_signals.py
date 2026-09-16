"""Need Reviewer: recurring concern-pattern detector across supervision meetings.

Adds need_review_signals — one row per named-person + concern-category mention
extracted from a meeting's AI analysis. When the same org_id + person_name +
concern_category combination reaches 3+ rows, the app raises a flag in that
meeting's Areas for Attention section. England/Wales/Scotland/NI scope only
(not Ofsted — "commissioning"/care-review concepts don't apply to schools).
"""

VERSION = "022_need_review_signals"

SQL = """
CREATE TABLE IF NOT EXISTS need_review_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    meeting_id UUID NOT NULL,
    person_name TEXT NOT NULL,
    concern_category TEXT NOT NULL,
    quote TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE need_review_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE need_review_signals FORCE ROW LEVEL SECURITY;

CREATE POLICY need_review_signals_rls ON need_review_signals
    USING (org_id::text = current_setting('app.current_org_id', true))
    WITH CHECK (org_id::text = current_setting('app.current_org_id', true));

CREATE INDEX IF NOT EXISTS idx_need_review_signals_lookup
    ON need_review_signals (org_id, person_name, concern_category);
"""


async def up(conn):
    await conn.execute(SQL)
