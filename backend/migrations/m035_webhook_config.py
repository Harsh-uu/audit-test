"""HR-system webhook integration (MVP): push a limited-field summary payload
(summary, achievements, actions, learning_needs + which staff member it's
about) to an org-configured URL when a meeting is signed off. Two tables:
webhook_configs (one row per org — URL + HMAC signing secret + on/off) and
webhook_deliveries (append-only attempt log, used for the Settings >
Integrations delivery log and the manual "Resend" action on failures).
"""

VERSION = "035_webhook_config"

SQL = """
CREATE TABLE IF NOT EXISTS webhook_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL UNIQUE,
    url TEXT NOT NULL DEFAULT '',
    secret TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_by_id UUID,
    created_by_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE webhook_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_configs FORCE ROW LEVEL SECURITY;

CREATE POLICY webhook_configs_rls ON webhook_configs
    USING (org_id::text = current_setting('app.current_org_id', true))
    WITH CHECK (org_id::text = current_setting('app.current_org_id', true));

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    meeting_id UUID,
    event TEXT NOT NULL DEFAULT 'meeting.signed_off',
    payload JSONB NOT NULL DEFAULT '{}',
    success BOOLEAN NOT NULL DEFAULT FALSE,
    http_status INTEGER,
    error_message TEXT,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE webhook_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_deliveries FORCE ROW LEVEL SECURITY;

CREATE POLICY webhook_deliveries_rls ON webhook_deliveries
    USING (org_id::text = current_setting('app.current_org_id', true))
    WITH CHECK (org_id::text = current_setting('app.current_org_id', true));

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_org_time ON webhook_deliveries (org_id, attempted_at DESC);
"""


async def up(conn):
    await conn.execute(SQL)
