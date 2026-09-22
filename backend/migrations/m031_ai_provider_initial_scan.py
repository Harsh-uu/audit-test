"""RCA follow-up (Sep 2026): a rescan's UPDATE was overwriting the SAME 4 AI
tracking columns the initial pass set, permanently destroying the evidence
needed to answer "what actually served the low-evidence first pass vs the
higher-evidence rescan". Adds a separate, never-overwritten "initial_*" set
so both the original scan and the latest scan's provider are visible side by
side going forward.
"""

VERSION = "031_ai_provider_initial_scan"

SQL = """
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS initial_ai_provider TEXT;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS initial_ai_fallback_used BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS initial_ai_fallback_reason TEXT;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS initial_ai_latency_ms INTEGER;
"""


async def up(conn):
    await conn.execute(SQL)
