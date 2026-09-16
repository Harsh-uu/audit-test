"""Resources page: curated downloads + course modules, shown to every org.

Global platform content (no org_id) — same visibility to every user regardless
of org, so no RLS needed here (nothing to scope by). Seeded/managed by the
agent directly via this migration as the user shares links, not through an
admin UI (no such request yet).
"""

VERSION = "023_resources"

SQL = """
CREATE TABLE IF NOT EXISTS resources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category TEXT NOT NULL CHECK (category IN ('download', 'course')),
    title TEXT NOT NULL,
    description TEXT,
    url TEXT NOT NULL,
    source_label TEXT,
    sort_order INT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

SEED_SQL = """
INSERT INTO resources (category, title, description, url, source_label, sort_order)
VALUES (
    'download',
    'Effective Supervision: A Practical Guide',
    'A practical guide to running effective, compliant supervision for adult social care managers and supervisors — covers the purpose of supervision, the supervisor''s role, and warning signs of ineffective practice.',
    'https://www.skillsforcare.org.uk/resources/documents/Support-for-leaders-and-managers/Managing-people/Supervision/Effective-supervision-guide.pdf',
    'Skills for Care',
    0
)
ON CONFLICT DO NOTHING;
"""


async def up(conn):
    await conn.execute(SQL)
    # Idempotency: only seed if the table is empty (no natural unique key on
    # url/title to ON CONFLICT against without adding a constraint just for this).
    count = await conn.fetchval("SELECT COUNT(*) FROM resources")
    if count == 0:
        await conn.execute(SEED_SQL)
