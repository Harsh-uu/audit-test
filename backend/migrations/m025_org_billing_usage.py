"""Super Admin billing/usage groundwork ahead of the real Stripe connection.

Adds manual placeholder billing fields to organisations (tier, included hours,
trial, Stripe fields — all hand-editable now, later synced from Stripe webhooks)
and an audio_duration_seconds column to meetings, captured going forward from
AssemblyAI's transcript.audio_duration at transcription time. Historical
meetings are deliberately NOT backfilled (test data, per product decision) —
usage reporting starts counting from the meetings recorded after this ships.
"""

VERSION = "025_org_billing_usage"

SQL = """
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS pricing_tier TEXT;
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS included_hours_monthly NUMERIC;
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS is_trial BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ;
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT;
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS stripe_subscription_status TEXT;
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS stripe_current_period_end TIMESTAMPTZ;
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS billing_notes TEXT;

ALTER TABLE meetings ADD COLUMN IF NOT EXISTS audio_duration_seconds NUMERIC;
"""


async def up(conn):
    await conn.execute(SQL)
