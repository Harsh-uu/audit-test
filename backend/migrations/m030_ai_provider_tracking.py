"""Adds AI provider tracking to analyses, per user request: track which AI
(Gemini vs OpenAI) actually served each meeting's evidence analysis (and
whether it was a fallback), surfaced in a new Super Admin AI Usage report —
not shown on individual meetings.
"""

VERSION = "030_ai_provider_tracking"

SQL = """
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS ai_provider TEXT;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS ai_fallback_used BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS ai_fallback_reason TEXT;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS ai_latency_ms INTEGER;
"""


async def up(conn):
    await conn.execute(SQL)
