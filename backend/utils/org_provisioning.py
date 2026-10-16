"""Shared organisation-provisioning core logic, used by BOTH:
  - the manual Super Admin "Create Org" + "Invite Admin" flows (routers/super_admin.py)
  - the new public Stripe self-serve onboarding flow (routers/public_signup.py,
    routers/cron_jobs.py's provisioning-retry sweep)
Kept as one shared implementation so a self-serve-created org is never
structurally different from a manually-created one, and so a fix to one
flow's org-creation/invite logic can't silently drift from the other's.
"""
import re as _re
import uuid
import secrets
import asyncio
import os
import html
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

VALID_JURISDICTIONS = ("england", "wales", "scotland", "northern_ireland", "ofsted")
NI_SERVICE_TYPES = ("residential", "domiciliary")
OFSTED_SERVICE_TYPES = ("early_years", "childrens_home", "school")
VALID_SERVICE_TYPES = NI_SERVICE_TYPES + OFSTED_SERVICE_TYPES


def slugify(name: str) -> str:
    return _re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def validate_jurisdiction_service_type(jurisdiction: Optional[str], service_type: Optional[str]):
    """Raises ValueError with a user-facing message on an invalid combo.
    Returns the normalised (jurisdiction, service_type) pair. Same rule the
    manual Super Admin 'Create Org' modal has always enforced."""
    jurisdiction = jurisdiction if jurisdiction in VALID_JURISDICTIONS else "england"
    service_type = service_type if service_type in VALID_SERVICE_TYPES else None
    if jurisdiction == "northern_ireland" and service_type not in NI_SERVICE_TYPES:
        raise ValueError("service_type ('residential' or 'domiciliary') is required for Northern Ireland organisations")
    if jurisdiction == "ofsted" and service_type not in OFSTED_SERVICE_TYPES:
        raise ValueError("service_type ('early_years', 'childrens_home' or 'school') is required for Ofsted organisations")
    return jurisdiction, service_type


async def create_org_core(
    conn, *, name: str, jurisdiction: str, service_type: Optional[str],
    pricing_tier: Optional[str] = None, included_hours_monthly=None,
    is_trial: bool = False, stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    stripe_subscription_status: Optional[str] = None,
    is_founding_member: bool = False,
    founding_price_lock_until=None,
    on_slug_conflict: str = "raise",
) -> dict:
    """Insert a new organisation row. Caller must already hold `conn` inside
    a with_admin() transaction block, and must have already validated
    jurisdiction/service_type via validate_jurisdiction_service_type().

    on_slug_conflict:
      - "raise"  (default, matches the original manual Super Admin behaviour
        exactly) — raises ValueError("Organisation with this name already
        exists") on a slug collision.
      - "suffix" — used by the self-serve/retry paths, where blocking a
        paying customer's onboarding over a name collision would be a much
        worse outcome than silently disambiguating the slug.
    """
    slug = slugify(name)
    now = datetime.now(timezone.utc).isoformat()
    org_id = str(uuid.uuid4())
    existing = await conn.fetchrow("SELECT id FROM organisations WHERE slug = $1", slug)
    if existing:
        if on_slug_conflict == "suffix":
            slug = f"{slug}-{org_id[:8]}"
        else:
            raise ValueError("Organisation with this name already exists")
    await conn.execute(
        """INSERT INTO organisations
           (id, name, slug, status, branding, jurisdiction, service_type, created_at,
            pricing_tier, included_hours_monthly, is_trial, stripe_customer_id,
            stripe_subscription_id, stripe_subscription_status, is_founding_member,
            founding_price_lock_until)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
        org_id, name.strip(), slug, "active", "{}", jurisdiction, service_type, now,
        pricing_tier, included_hours_monthly, is_trial, stripe_customer_id,
        stripe_subscription_id, stripe_subscription_status, is_founding_member,
        founding_price_lock_until,
    )
    return {
        "id": org_id, "name": name.strip(), "slug": slug, "status": "active",
        "jurisdiction": jurisdiction, "service_type": service_type, "created_at": now,
    }


def build_invite_email(name: str, org_name: str, invite_link: str, role_label: str = "Organisation Admin") -> str:
    name = html.escape(name or "")
    org_name = html.escape(org_name or "")
    role_label = html.escape(role_label or "Organisation Admin")
    return f"""<!DOCTYPE html>
<html lang="en">
<body style="margin:0;padding:0;background:#F1F5F9;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 16px;">
  <tr><td align="center">
    <table width="520" cellpadding="0" cellspacing="0" style="background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 32px rgba(0,0,0,0.10);">
      <tr><td style="background:#1E3A8A;padding:32px 40px;">
        <p style="color:white;margin:0;font-size:24px;font-weight:700;">1two.one</p>
        <p style="color:rgba(255,255,255,0.60);margin:6px 0 0;font-size:13px;">Care Supervision Platform</p>
      </td></tr>
      <tr><td style="padding:40px 40px 32px;">
        <h2 style="color:#111827;font-size:20px;margin:0 0 20px;">You've been invited to join {org_name}</h2>
        <p style="color:#4B5563;font-size:15px;line-height:1.7;margin:0 0 10px;">Hi {name},</p>
        <p style="color:#4B5563;font-size:15px;line-height:1.7;margin:0 0 32px;">
          Your account has been created on <strong>1two.one</strong> as a
          <strong>{role_label}</strong> for <strong>{org_name}</strong>.
          Click below to set your password (expires in 72 hours).
        </p>
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr><td align="center" style="padding-bottom:32px;">
            <a href="{invite_link}" style="background:#1E3A8A;color:white;padding:14px 40px;text-decoration:none;border-radius:8px;font-weight:600;font-size:15px;display:inline-block;">
              Accept Invitation &rarr;
            </a>
          </td></tr>
        </table>
        <p style="color:#9CA3AF;font-size:13px;text-align:center;margin:0;">If you weren't expecting this, safely ignore this email.</p>
      </td></tr>
      <tr><td style="padding:20px 40px;border-top:1px solid #F3F4F6;background:#F9FAFB;">
        <p style="color:#9CA3AF;font-size:12px;margin:0;text-align:center;">&copy; 2025 1two.one</p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


async def invite_user_core(conn, *, org_id: str, org_name: str, email: str, name: str, role: str = "admin") -> dict:
    """Create the disabled user + 72h invitation row. DB-only — caller sends
    the actual email afterward via send_invite_email(), outside the
    transaction, same pattern the original manual "Invite Admin" flow used.
    Used for org-admin invites (Super Admin / Stripe self-serve onboarding)
    AND regular staff invites (org admins/managers inviting their own team —
    see routers/org.py's /invite-user). must_change_password=TRUE mirrors the
    is_active=FALSE "pending invite" signal used everywhere else in the app
    (people-stats pending badge, revoke-vs-deactivate branching in
    routers/admin.py's delete_user) — accept_invite() flips both back on
    acceptance.
    Raises ValueError if the email is already registered."""
    now = datetime.now(timezone.utc).isoformat()
    user_id = str(uuid.uuid4())
    invite_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()

    existing = await conn.fetchrow("SELECT id FROM users WHERE email = $1", email.lower())
    if existing:
        raise ValueError("An account with this email already exists")

    from routers.auth import hash_password
    from utils import supabase_auth
    await conn.execute(
        """INSERT INTO users (id, email, password_hash, name, role, org_id, is_active, must_change_password, created_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
        user_id, email.lower(), await hash_password(secrets.token_urlsafe(32)),
        name.strip(), role, org_id, False, True, now,
    )
    await conn.execute(
        "INSERT INTO invitations (id, org_id, user_id, token, expires_at, created_at) VALUES ($1,$2,$3,$4,$5,$6)",
        invite_id, org_id, user_id, token, expires_at, now,
    )
    try:
        await supabase_auth.create_user(user_id, email.lower())
        await conn.execute("UPDATE users SET supabase_migrated=TRUE WHERE id=$1", user_id)
    except Exception as exc:
        logger.error("Supabase Auth provisioning failed for invited user %s: %s", email, exc)

    frontend_url = os.environ.get("FRONTEND_URL", "")
    invite_link = f"{frontend_url}/accept-invite?token={token}"
    return {"user_id": user_id, "invite_link": invite_link, "token": token}


async def send_invite_email(email: str, name: str, org_name: str, invite_link: str, role_label: str = "Organisation Admin") -> bool:
    """Best-effort Resend send — never raises. Returns whether it actually sent."""
    try:
        import resend
        resend.api_key = os.environ.get("RESEND_API_KEY", "")
        html_body = build_invite_email(name, org_name, invite_link, role_label)
        await asyncio.to_thread(resend.Emails.send, {
            "from": os.environ.get("SENDER_EMAIL", "noreply@notify.1two.one"),
            "to": [email.lower()],
            "subject": f"You've been invited to join {org_name} on 1two.one",
            "html": html_body,
        })
        logger.info(f"Invite email sent to {email}")
        return True
    except Exception as e:
        logger.warning(f"Invite email failed (user still created): {e}")
        return False
