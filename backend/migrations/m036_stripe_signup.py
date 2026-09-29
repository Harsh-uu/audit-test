"""Self-serve Stripe subscription checkout support tables + org billing
founding-member fields. Public flow: /api/public/checkout ->
/api/public/checkout/verify -> /api/public/onboarding/complete, backed by
Stripe webhooks at /api/stripe/webhook. These new tables are deliberately
NOT RLS-scoped — they hold pre-org signup data (no org context exists yet
at checkout time) and are only ever touched via database.with_admin(),
the same trust boundary already used for `organisations`/`invitations`
during any account-creation flow.
"""

VERSION = "036_stripe_signup"

SQL = """
CREATE TABLE IF NOT EXISTS pending_signups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stripe_checkout_session_id TEXT NOT NULL UNIQUE,
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    tier TEXT NOT NULL,
    is_founding BOOLEAN NOT NULL DEFAULT TRUE,
    founding_price_lock_until TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'paid',
    org_id UUID,
    reminder_sent_at TIMESTAMPTZ,
    alerted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pending_signups_status ON pending_signups (status, org_id);
CREATE INDEX IF NOT EXISTS idx_pending_signups_reminder ON pending_signups (founding_price_lock_until) WHERE reminder_sent_at IS NULL;

CREATE TABLE IF NOT EXISTS stripe_events_processed (
    stripe_event_id TEXT PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- `payload` (name/email/organisation_name/jurisdiction/service_type) is not
-- part of the original spec's column list but is required for the
-- provisioning-retry cron to actually be able to retry org creation + the
-- admin invite with the customer's real submitted data, instead of only the
-- Stripe-side ids already sitting on pending_signups.
CREATE TABLE IF NOT EXISTS provisioning_failures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pending_signup_id UUID NOT NULL REFERENCES pending_signups(id) ON DELETE CASCADE,
    error TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempted_at TIMESTAMPTZ,
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_provisioning_failures_unresolved ON provisioning_failures (resolved, attempt_count);

ALTER TABLE organisations ADD COLUMN IF NOT EXISTS is_founding_member BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS founding_price_lock_until TIMESTAMPTZ;
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS stripe_subscription_id TEXT;
"""


async def up(conn):
    await conn.execute(SQL)
