"""EULA acceptance tracking ahead of the finalized legal text.

Adds a small `eula_versions` table (global platform content, no org_id —
same pattern as m023_resources.py) holding the current EULA text, plus
eula_accepted_version/eula_accepted_at/eula_decline_count on `users` so
acceptance is logged per-account (timestamp + version, per product
requirement — "log the accepted eula against their account").

Existing users (all demo/test accounts as of this ship date, per explicit
product decision) are backfilled to "already accepted" so they are NOT
disrupted — only brand-new accounts created from this point on see the
gate. Future EULA version bumps (a new row in eula_versions with a higher
version + is_active=TRUE) will naturally re-gate EVERYONE, including these
backfilled accounts, since their eula_accepted_version will then be below
the new active version — that's the whole point of versioning it now.
"""

VERSION = "026_eula"

PLACEHOLDER_CONTENT = (
    "END USER LICENCE AGREEMENT — PLACEHOLDER\n\n"
    "This is a temporary placeholder EULA for Supervision 2.0 (1two.one) while the "
    "final legal text is being drafted. It will be replaced before this is relied "
    "upon for real users. By continuing, you acknowledge this platform is used to "
    "record, transcribe and analyse supervision meetings for regulatory compliance "
    "purposes, and that your organisation is responsible for obtaining any consents "
    "required from meeting participants prior to recording."
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS eula_versions (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE,
    content TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_eula_versions_active ON eula_versions(is_active) WHERE is_active;

ALTER TABLE users ADD COLUMN IF NOT EXISTS eula_accepted_version INTEGER;
ALTER TABLE users ADD COLUMN IF NOT EXISTS eula_accepted_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS eula_decline_count INTEGER NOT NULL DEFAULT 0;
"""


async def up(conn):
    await conn.execute(SCHEMA_SQL)

    existing = await conn.fetchval("SELECT id FROM eula_versions WHERE version = 1")
    if not existing:
        await conn.execute(
            """INSERT INTO eula_versions (id, version, content, is_active)
               VALUES (gen_random_uuid()::text, 1, $1, TRUE)""",
            PLACEHOLDER_CONTENT,
        )

    # Backfill: existing accounts (demo/test data) are marked as already on
    # version 1 so they are never gated by this initial rollout.
    await conn.execute(
        """UPDATE users SET eula_accepted_version = 1, eula_accepted_at = now()
           WHERE eula_accepted_version IS NULL"""
    )
