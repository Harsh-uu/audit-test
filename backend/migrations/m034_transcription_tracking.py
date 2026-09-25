"""Track AssemblyAI transcription telemetry (which speech model actually served
each transcript, and how long it took) so Super Admin can see a transcription
usage report — mirrors the existing ai_provider/ai_latency_ms tracking already
in place for the Gemini/OpenAI evidence-analysis step.
"""

VERSION = "034_transcription_tracking"

SQL = """
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS speech_model_used TEXT;
ALTER TABLE transcripts ADD COLUMN IF NOT EXISTS latency_ms INTEGER;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS failed_stage TEXT;
"""


async def up(conn):
    await conn.execute(SQL)
