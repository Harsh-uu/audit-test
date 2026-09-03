"""
Phase 4: one-time batch send of the forced password-reset email to every
existing user still on bcrypt (supabase_password_set = FALSE). Reuses the
exact same password_reset_tokens + Resend template as /api/auth/forgot-password
(routers/auth.py) — completing the reset via /reset-password (already wired
to Supabase Auth in Phase 3) is what actually flips supabase_password_set.

Safe to re-run: skips users who already migrated since the last run.

Usage: python3 scripts/send_supabase_migration_emails.py
"""
import asyncio
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg
import resend
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")


def _send_reset_email(email: str, reset_link: str) -> bool:
    resend.api_key = os.environ.get("RESEND_API_KEY", "")
    try:
        resend.Emails.send({
            "from": "Supervision 2 <noreply@notify.1two.one>",
            "to": [email],
            "subject": "Action required: reset your password",
            "html": (
                "<div style='font-family:Poppins,sans-serif;max-width:480px;margin:0 auto;"
                "padding:32px 24px;background:#f8fafc;border-radius:12px;'>"
                "<h2 style='color:#1E3A8A;font-size:22px;margin-bottom:8px;'>Please reset your password</h2>"
                "<p style='color:#475569;font-size:15px;margin-bottom:24px;'>We've upgraded how "
                "sign-in works. Click the button below to set a new password and keep using your "
                "account. This link expires in <strong>1 hour</strong>.</p>"
                f"<a href='{reset_link}' style='display:inline-block;background:#1E3A8A;color:#fff;"
                "text-decoration:none;padding:12px 28px;border-radius:8px;font-size:15px;"
                "font-weight:600;'>Reset Password</a>"
                "<p style='color:#94a3b8;font-size:12px;margin-top:28px;'>"
                "If you have any questions, contact your organisation administrator.</p>"
                "</div>"
            ),
        })
        return True
    except Exception as exc:
        print(f"  EMAIL FAILED for {email}: {exc}")
        return False


async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], ssl="require")
    try:
        rows = await conn.fetch(
            "SELECT email FROM users WHERE is_active = TRUE AND supabase_password_set = FALSE"
        )
        print(f"{len(rows)} user(s) to email")
        sent, failed = 0, 0
        for row in rows:
            email = row["email"]
            token = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
            await conn.execute("DELETE FROM password_reset_tokens WHERE email = $1", email)
            await conn.execute(
                "INSERT INTO password_reset_tokens (token, email, expires_at, used) VALUES ($1,$2,$3,$4)",
                token, email, expires_at, False,
            )
            reset_link = f"{FRONTEND_URL}/reset-password?token={token}"
            if _send_reset_email(email, reset_link):
                sent += 1
                print(f"  OK   {email}")
            else:
                failed += 1
        print(f"Done: {sent} sent, {failed} failed")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
