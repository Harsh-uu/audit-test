"""One-off: upload the 9 free-course PDFs to Supabase Storage and insert
their `resources` rows (category='course'). Safe to re-run — deletes any
existing course rows with a matching sort_order first (idempotent upsert).
"""
import asyncio
import os
import sys
import uuid

import asyncpg
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend")
be = dotenv_values("/app/backend/.env")
os.environ.update(be)

from utils.supabase_storage import put_document  # noqa: E402

MODULES = [
    (1, "module-1.pdf", "Module 1: What Supervision Is For",
     "Defines the three core functions of effective, transformative supervision and contrasts it with superficial, tick-box practice."),
    (2, "module-2.pdf", "Module 2: Preparing Properly",
     "How outstanding supervisors prepare before a session so the conversation is honest, contextualised and thorough."),
    (3, "module-3.pdf", "Module 3: Conducting the Session",
     "Essential in-session skills — presence, active listening, a flexible structure and the GROW coaching model."),
    (4, "module-4.pdf", "Module 4: Challenging Conversations",
     "How to prepare for and handle difficult supervision conversations with directness and empathy."),
    (5, "module-5.pdf", "Module 5: Documentation & Follow-Up",
     "Why accurate, timely records and active follow-up on agreed actions matter for evidence and accountability."),
    (6, "module-6.pdf", "Module 6: Frequency & New to Role",
     "Tailoring supervision frequency to individual need — with extra care for new starters and probation."),
    (7, "module-7.pdf", "Module 7: Measuring the Difference",
     "How to measure supervision's real impact — retention, incidents, action completion and supervisee feedback."),
    (8, "module-8.pdf", "Bonus Module: Supervision to Appraisal",
     "How consistent, well-documented supervision throughout the year builds the foundation for a strong annual appraisal."),
    (9, "module-9.pdf", "Bonus Module: Active Listening In Depth",
     "The mechanics of active listening — open questions, paraphrasing, silence and mirroring — in practical depth."),
]


async def main():
    conn = await asyncpg.connect(be["DATABASE_URL"], ssl="require")
    await conn.execute("DELETE FROM resources WHERE category='course'")
    for sort_order, filename, title, description in MODULES:
        with open(f"/tmp/course_modules/{filename}", "rb") as f:
            data = f.read()
        storage_path = f"course/{filename}"
        await put_document(storage_path, data, "application/pdf")
        resource_id = uuid.uuid4()
        await conn.execute(
            """INSERT INTO resources (id, category, title, description, url, storage_path, content_type, sort_order, is_active)
               VALUES ($1,'course',$2,$3,$4,$5,'application/pdf',$6,TRUE)""",
            resource_id, title, description, f"/api/resources/course/{resource_id}/file", storage_path, sort_order,
        )
        print(f"inserted [{sort_order}] {title} -> {resource_id}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
