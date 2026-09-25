import uuid
import re as _re
import secrets
import asyncio
import os
import logging
import html
import calendar
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from datetime import datetime, timezone, timedelta
from typing import Optional
from deps import get_db, get_current_user
import database
from utils.supabase_storage import delete_audio_batch

router = APIRouter()
logger = logging.getLogger(__name__)


def _slugify(name: str) -> str:
    return _re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def _require_super_admin(current_user):
    if current_user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin only")


VALID_JURISDICTIONS = ("england", "wales", "scotland", "northern_ireland", "ofsted")
NI_SERVICE_TYPES = ("residential", "domiciliary")
OFSTED_SERVICE_TYPES = ("early_years", "childrens_home", "school")
VALID_SERVICE_TYPES = NI_SERVICE_TYPES + OFSTED_SERVICE_TYPES

# Placeholder pricing tiers ahead of the real Stripe connection — manually set
# per org for now (super admin picks a tier, included_hours_monthly auto-fills
# but stays editable for founding-member/custom deals). Mirrors supervision2.co.uk/#pricing.
PRICING_TIERS = {
    "starter":    {"label": "Starter",    "included_hours": 10},
    "growth":     {"label": "Growth",     "included_hours": 30},
    "scale":      {"label": "Scale",      "included_hours": 70},
    "enterprise": {"label": "Enterprise", "included_hours": None},  # tailored allocation, no fixed cap
}
VALID_STRIPE_STATUSES = ("active", "trialing", "past_due", "canceled", "unpaid", "incomplete")


def _billing_period(anchor: datetime, now: datetime) -> tuple:
    """Return (period_start, period_end) for the monthly billing cycle anchored
    to `anchor`'s day-of-month (the org's signup date) that `now` falls within —
    per-org usage is tracked against each org's own renewal date, not a shared
    calendar month. Clamps to the last day of shorter months (e.g. day 31
    anchor -> Feb 28)."""
    def _clamped(year, month, day):
        last_day = calendar.monthrange(year, month)[1]
        return anchor.replace(year=year, month=month, day=min(day, last_day))

    anchor_day = anchor.day
    start = _clamped(now.year, now.month, anchor_day)
    if start > now:
        prev_month = now.month - 1 or 12
        prev_year = now.year - 1 if now.month == 1 else now.year
        start = _clamped(prev_year, prev_month, anchor_day)
    end_month = start.month + 1 if start.month < 12 else 1
    end_year = start.year + 1 if start.month == 12 else start.year
    end = _clamped(end_year, end_month, anchor_day)
    return start, end


class CreateOrgRequest(BaseModel):
    name: str
    jurisdiction: Optional[str] = "england"
    service_type: Optional[str] = None  # required for northern_ireland


class UpdateOrgRequest(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    jurisdiction: Optional[str] = None
    service_type: Optional[str] = None


class UpdateOrgBillingRequest(BaseModel):
    pricing_tier: Optional[str] = None
    included_hours_monthly: Optional[float] = None
    is_trial: Optional[bool] = None
    trial_ends_at: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_status: Optional[str] = None
    stripe_current_period_end: Optional[str] = None
    billing_notes: Optional[str] = None


class OrgBrandingUpdate(BaseModel):
    primary_color: Optional[str] = None
    logo_url: Optional[str] = None


class CreateOrgUserRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: str = "manager"


class UpdateOrgUserRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    password: Optional[str] = None


def _enrich_org(org, usage_rows, now) -> dict:
    """Shared enrichment: billing-cycle usage math for one org row, given its
    own (created_at, audio_duration_seconds) meeting rows. Used by both the
    list and single-org endpoints so the math can't drift between them."""
    anchor = datetime.fromisoformat(org["created_at"]) if org["created_at"] else now
    period_start, period_end = _billing_period(anchor, now)
    cumulative_hours = round(sum(secs for _, secs in usage_rows) / 3600, 2)
    period_hours = round(sum(secs for ts, secs in usage_rows if period_start <= ts < period_end) / 3600, 2)
    included_hours = org["included_hours_monthly"]
    return {
        "id": org["id"], "name": org["name"], "slug": org["slug"],
        "status": org["status"], "jurisdiction": org.get("jurisdiction") or "england",
        "service_type": org.get("service_type"),
        "created_at": org["created_at"],
        "user_count": org["user_count"], "meeting_count": org["meeting_count"],
        "pricing_tier": org.get("pricing_tier"),
        "included_hours_monthly": float(included_hours) if included_hours is not None else None,
        "is_trial": org.get("is_trial", False),
        "trial_ends_at": org.get("trial_ends_at"),
        "stripe_customer_id": org.get("stripe_customer_id"),
        "stripe_subscription_status": org.get("stripe_subscription_status"),
        "stripe_current_period_end": org.get("stripe_current_period_end"),
        "billing_notes": org.get("billing_notes"),
        "current_period_start": period_start.isoformat(),
        "current_period_end": period_end.isoformat(),
        "current_period_hours": period_hours,
        "cumulative_hours": cumulative_hours,
        "hours_overage": included_hours is not None and period_hours > float(included_hours),
    }


@router.get("/orgs")
async def list_orgs(current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    now = datetime.now(timezone.utc)
    async with database.with_admin() as conn:
        # Batched: one query with per-org counts as correlated subqueries,
        # instead of 2 extra round-trips per org (was 2N+1 queries total).
        org_rows = await conn.fetch(
            """SELECT o.*,
                      (SELECT COUNT(*) FROM users u WHERE u.org_id = o.id) AS user_count,
                      (SELECT COUNT(*) FROM meetings m WHERE m.org_id = o.id) AS meeting_count
               FROM organisations o ORDER BY o.name ASC"""
        )
        # Audio usage rows, batched for ALL orgs in one query rather than N queries —
        # only meetings with a captured duration count (historical meetings recorded
        # before this feature shipped are NOT backfilled, by design).
        usage_rows = await conn.fetch(
            "SELECT org_id, created_at, audio_duration_seconds FROM meetings WHERE audio_duration_seconds IS NOT NULL"
        )
        usage_by_org = {}
        for r in usage_rows:
            ts = datetime.fromisoformat(r["created_at"]) if r["created_at"] else now
            usage_by_org.setdefault(r["org_id"], []).append((ts, float(r["audio_duration_seconds"])))

        result = [_enrich_org(org, usage_by_org.get(org["id"], []), now) for org in org_rows]
    return result


@router.get("/orgs/{org_id}")
async def get_org(org_id: str, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    now = datetime.now(timezone.utc)
    async with database.with_admin() as conn:
        org = await conn.fetchrow(
            """SELECT o.*,
                      (SELECT COUNT(*) FROM users u WHERE u.org_id = o.id) AS user_count,
                      (SELECT COUNT(*) FROM meetings m WHERE m.org_id = o.id) AS meeting_count
               FROM organisations o WHERE o.id = $1""",
            org_id,
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")
        usage_rows = await conn.fetch(
            "SELECT created_at, audio_duration_seconds FROM meetings WHERE org_id=$1 AND audio_duration_seconds IS NOT NULL",
            org_id,
        )
    usage = [(datetime.fromisoformat(r["created_at"]) if r["created_at"] else now, float(r["audio_duration_seconds"])) for r in usage_rows]
    return _enrich_org(org, usage, now)


@router.get("/orgs/{org_id}/usage-history")
async def org_usage_history(org_id: str, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    now = datetime.now(timezone.utc)
    async with database.with_admin() as conn:
        org = await conn.fetchrow("SELECT created_at FROM organisations WHERE id=$1", org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")
        rows = await conn.fetch(
            "SELECT created_at, audio_duration_seconds FROM meetings WHERE org_id=$1 AND audio_duration_seconds IS NOT NULL",
            org_id,
        )
    anchor = datetime.fromisoformat(org["created_at"]) if org["created_at"] else now
    usage = [
        (datetime.fromisoformat(r["created_at"]) if r["created_at"] else now, float(r["audio_duration_seconds"]))
        for r in rows
    ]
    cycles = []
    cursor_now = now
    for _ in range(12):
        period_start, period_end = _billing_period(anchor, cursor_now)
        seconds = sum(secs for ts, secs in usage if period_start <= ts < period_end)
        cycles.append({
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "hours": round(seconds / 3600, 2),
        })
        cursor_now = period_start - timedelta(seconds=1)
        if cursor_now < anchor:
            break
    cycles.reverse()
    return cycles


@router.patch("/orgs/{org_id}/billing")
async def update_org_billing(org_id: str, data: UpdateOrgBillingRequest, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    updates = {}
    if data.pricing_tier is not None:
        if data.pricing_tier and data.pricing_tier not in PRICING_TIERS:
            raise HTTPException(status_code=400, detail=f"Invalid pricing_tier. Must be one of: {', '.join(PRICING_TIERS)}")
        updates["pricing_tier"] = data.pricing_tier or None
    if data.included_hours_monthly is not None:
        updates["included_hours_monthly"] = data.included_hours_monthly if data.included_hours_monthly >= 0 else None
    if data.is_trial is not None:
        updates["is_trial"] = data.is_trial
    if data.trial_ends_at is not None:
        updates["trial_ends_at"] = data.trial_ends_at or None
    if data.stripe_customer_id is not None:
        updates["stripe_customer_id"] = data.stripe_customer_id.strip() or None
    if data.stripe_subscription_status is not None:
        if data.stripe_subscription_status and data.stripe_subscription_status not in VALID_STRIPE_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid stripe_subscription_status. Must be one of: {', '.join(VALID_STRIPE_STATUSES)}")
        updates["stripe_subscription_status"] = data.stripe_subscription_status or None
    if data.stripe_current_period_end is not None:
        updates["stripe_current_period_end"] = data.stripe_current_period_end or None
    if data.billing_notes is not None:
        updates["billing_notes"] = data.billing_notes.strip() or None
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    async with database.with_admin() as conn:
        org = await conn.fetchrow("SELECT id FROM organisations WHERE id=$1", org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")
        set_clause = ", ".join(f"{k}=${i + 2}" for i, k in enumerate(updates.keys()))
        await conn.execute(
            f"UPDATE organisations SET {set_clause} WHERE id=$1",
            org_id, *updates.values(),
        )
    return {"message": "Billing info updated"}


@router.post("/orgs")
async def create_org(data: CreateOrgRequest, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    slug = _slugify(data.name)
    now = datetime.now(timezone.utc).isoformat()
    org_id = str(uuid.uuid4())
    async with database.with_admin() as conn:
        existing = await conn.fetchrow("SELECT id FROM organisations WHERE slug = $1", slug)
        if existing:
            raise HTTPException(status_code=400, detail="Organisation with this name already exists")
        jurisdiction = data.jurisdiction if data.jurisdiction in VALID_JURISDICTIONS else "england"
        service_type = data.service_type if data.service_type in VALID_SERVICE_TYPES else None
        # NI orgs must declare service_type (residential/domiciliary) — checked against the
        # correct family, not just VALID_SERVICE_TYPES, since that tuple now also contains
        # Ofsted's service_type values and the two families must never cross-contaminate.
        if jurisdiction == "northern_ireland" and service_type not in NI_SERVICE_TYPES:
            raise HTTPException(status_code=400, detail="service_type ('residential' or 'domiciliary') is required for Northern Ireland organisations")
        # Ofsted orgs must declare service_type (early_years/childrens_home/school)
        if jurisdiction == "ofsted" and service_type not in OFSTED_SERVICE_TYPES:
            raise HTTPException(status_code=400, detail="service_type ('early_years', 'childrens_home' or 'school') is required for Ofsted organisations")
        await conn.execute(
            "INSERT INTO organisations (id, name, slug, status, branding, jurisdiction, service_type, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            org_id, data.name.strip(), slug, "active", "{}", jurisdiction, service_type, now,
        )
    return {"id": org_id, "name": data.name.strip(), "slug": slug, "status": "active", "jurisdiction": jurisdiction, "service_type": service_type, "created_at": now}


@router.patch("/orgs/{org_id}")
async def update_org(org_id: str, data: UpdateOrgRequest, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    updates = {}
    if data.name is not None:
        updates["name"] = data.name.strip()
        updates["slug"] = _slugify(data.name)
    if data.status in ("active", "suspended"):
        updates["status"] = data.status
    if data.jurisdiction in VALID_JURISDICTIONS:
        updates["jurisdiction"] = data.jurisdiction
    if data.service_type in VALID_SERVICE_TYPES:
        updates["service_type"] = data.service_type
    elif data.service_type == "" or (data.jurisdiction and data.jurisdiction not in ("northern_ireland", "ofsted")):
        # Clear service_type when switching away from NI/Ofsted
        updates["service_type"] = None

    # If switching TO northern_ireland or ofsted, must provide a valid service_type for
    # that jurisdiction's own family (not just any non-empty value — NI and Ofsted's
    # service_type values must never cross-contaminate each other).
    effective_jurisdiction = updates.get("jurisdiction") or data.jurisdiction
    resolved_service_type = updates["service_type"] if "service_type" in updates else data.service_type
    if effective_jurisdiction == "northern_ireland" and resolved_service_type not in NI_SERVICE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="service_type ('residential' or 'domiciliary') is required for Northern Ireland organisations",
        )
    if effective_jurisdiction == "ofsted" and resolved_service_type not in OFSTED_SERVICE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="service_type ('early_years', 'childrens_home' or 'school') is required for Ofsted organisations",
        )

    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    set_clause = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates.keys()))
    async with database.with_admin() as conn:
        await conn.execute(f"UPDATE organisations SET {set_clause} WHERE id=$1", *([org_id] + list(updates.values())))
        from utils.standards_cache import invalidate_org
        invalidate_org(org_id)
    return {"message": "Organisation updated"}


@router.delete("/orgs/{org_id}", status_code=200)
async def delete_org(org_id: str, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    async with database.with_admin() as conn:
        org = await conn.fetchrow("SELECT name FROM organisations WHERE id = $1", org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")
        org_name = org["name"]
        totals = {}

        # Get meeting IDs
        meeting_ids = [r["id"] for r in await conn.fetch("SELECT id FROM meetings WHERE org_id = $1", org_id)]

        # Any audio must be deleted from storage too — fetch paths before the rows
        # disappear below. delete_audio() is idempotent on an already-removed path.
        audio_paths = []
        if meeting_ids:
            audio_paths = [
                r["storage_path"] for r in await conn.fetch(
                    "SELECT storage_path FROM audio_files WHERE meeting_id = ANY($1::uuid[]) AND storage_path IS NOT NULL",
                    meeting_ids,
                )
            ]

        if meeting_ids:
            for table in ["transcripts", "analyses", "audit_logs", "reviewer_comments", "review_edits", "audio_files", "evidence_feedback", "jobs"]:
                result = await conn.execute(f"DELETE FROM {table} WHERE meeting_id = ANY($1::uuid[])", meeting_ids)
                totals[table] = int(result.split()[-1])

        for table in ["meetings", "users", "schedules", "meeting_types", "standards_documents",
                       "supervision_uploads", "invitations", "settings"]:
            result = await conn.execute(f"DELETE FROM {table} WHERE org_id = $1", org_id)
            totals[table] = int(result.split()[-1])

        await conn.execute("DELETE FROM organisations WHERE id = $1", org_id)

    if audio_paths:
        try:
            # PERF-005: one batched Supabase Storage call for all of this org's
            # audio files, instead of one delete request per file.
            await delete_audio_batch(audio_paths)
        except Exception as e:
            logger.error("Failed to delete audio from storage during org '%s' deletion: paths=%s error=%s", org_id, audio_paths, e)

    logger.info("Deleted org '%s' (%s): %s", org_name, org_id, totals)
    return {"message": f"Organisation '{org_name}' permanently deleted", "deleted": totals}


@router.get("/orgs/{org_id}/users")
async def list_org_users(org_id: str, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    async with database.with_admin() as conn:
        rows = await conn.fetch(
            "SELECT id, org_id, email, name, role, is_active, team_id, setting_id, created_at FROM users WHERE org_id = $1 ORDER BY name ASC",
            org_id,
        )
    return [dict(r) for r in rows]


@router.post("/orgs/{org_id}/users")
async def create_org_user(org_id: str, data: CreateOrgUserRequest, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    from routers.auth import hash_password, validate_password_strength
    from utils import supabase_auth
    validate_password_strength(data.password)
    role = data.role if data.role in ["admin", "manager", "attendee", "shared_reviewer"] else "manager"
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Phase 1: local insert only — commits and closes before any network call,
    # so the DB session never sits idle-in-transaction waiting on Supabase Auth
    # (which can exceed idle_in_transaction_session_timeout under load).
    async with database.with_admin() as conn:
        org = await conn.fetchrow("SELECT id FROM organisations WHERE id = $1", org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")
        existing = await conn.fetchrow("SELECT id FROM users WHERE email = $1", data.email.lower())
        if existing:
            raise HTTPException(status_code=400, detail="Email already exists")
        await conn.execute(
            """INSERT INTO users (id, email, password_hash, name, role, org_id, is_active, must_change_password, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            user_id, data.email.lower(), await hash_password(data.password),
            data.name.strip(), role, org_id, True, True, now,
        )

    # Phase 2: Supabase Auth network calls — deliberately outside any open
    # transaction. A failure here is logged and left for retry; the user can
    # still log in locally via password_hash until supabase_migrated is set.
    try:
        await supabase_auth.create_user(user_id, data.email.lower())
        await supabase_auth.set_password(user_id, data.password)
    except Exception as exc:
        logger.error("Supabase Auth provisioning failed for org user %s: %s", data.email, exc)
    else:
        # Phase 3: short follow-up transaction to persist the migration flags.
        async with database.with_admin() as conn:
            await conn.execute("UPDATE users SET supabase_migrated=TRUE, supabase_password_set=TRUE WHERE id=$1", user_id)
    return {"id": user_id, "email": data.email.lower(), "name": data.name.strip(), "role": role, "org_id": org_id}


@router.patch("/orgs/{org_id}/users/{user_id}")
async def update_org_user(org_id: str, user_id: str, data: UpdateOrgUserRequest, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    updates = {}
    if data.name is not None:
        updates["name"] = data.name.strip()
    if data.role is not None:
        if data.role not in {"admin", "manager", "attendee", "shared_reviewer"}:
            raise HTTPException(status_code=400, detail="Invalid role")
        updates["role"] = data.role
    if data.password:
        from routers.auth import hash_password, validate_password_strength
        validate_password_strength(data.password)
        updates["password_hash"] = await hash_password(data.password)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    if data.email is not None:
        async with database.with_admin() as conn:
            clash = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1 AND id <> $2", data.email.lower(), user_id
            )
            if clash:
                raise HTTPException(status_code=400, detail="Email already in use")
        updates["email"] = data.email.lower()

    set_parts = [f"{k}=${i+2}" for i, k in enumerate(updates.keys())]
    async with database.with_admin() as conn:
        u = await conn.fetchrow("SELECT id FROM users WHERE id = $1 AND org_id = $2", user_id, org_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found in this organisation")
        await conn.execute(
            f"UPDATE users SET {', '.join(set_parts)} WHERE id=$1",
            user_id, *list(updates.values()),
        )
        row = await conn.fetchrow(
            "SELECT id, org_id, email, name, role, is_active, team_id, setting_id, created_at FROM users WHERE id=$1", user_id
        )
    return dict(row)


@router.delete("/orgs/{org_id}/users/{user_id}", status_code=200)
async def delete_org_user(org_id: str, user_id: str, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    async with database.with_admin() as conn:
        u = await conn.fetchrow("SELECT name FROM users WHERE id = $1 AND org_id = $2", user_id, org_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        sched = await conn.execute("DELETE FROM schedules WHERE staff_user_id = $1", user_id)
        await conn.execute("DELETE FROM users WHERE id = $1", user_id)
    return {"message": f"User '{u['name']}' deleted"}


def _build_invite_email(name: str, org_name: str, invite_link: str) -> str:
    name = html.escape(name or "")
    org_name = html.escape(org_name or "")
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
          Your account has been created on <strong>1two.one</strong> as an
          <strong>Organisation Admin</strong> for <strong>{org_name}</strong>.
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


class InviteAdminRequest(BaseModel):
    email: EmailStr
    name: str


@router.post("/orgs/{org_id}/invite")
async def invite_org_admin(org_id: str, data: InviteAdminRequest, current_user=Depends(get_current_user)):
    _require_super_admin(current_user)
    now = datetime.now(timezone.utc).isoformat()
    user_id = str(uuid.uuid4())
    invite_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()

    async with database.with_admin() as conn:
        org = await conn.fetchrow("SELECT name FROM organisations WHERE id = $1", org_id)
        if not org:
            raise HTTPException(status_code=404, detail="Organisation not found")
        existing = await conn.fetchrow("SELECT id FROM users WHERE email = $1", data.email.lower())
        if existing:
            raise HTTPException(status_code=400, detail="An account with this email already exists")

        from routers.auth import hash_password
        from utils import supabase_auth
        await conn.execute(
            """INSERT INTO users (id, email, password_hash, name, role, org_id, is_active, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
            user_id, data.email.lower(), await hash_password(secrets.token_urlsafe(32)),
            data.name.strip(), "admin", org_id, False, now,
        )
        await conn.execute(
            "INSERT INTO invitations (id, org_id, user_id, token, expires_at, created_at) VALUES ($1,$2,$3,$4,$5,$6)",
            invite_id, org_id, user_id, token, expires_at, now,
        )
        # No password set yet — real password is set in accept-invite below.
        try:
            await supabase_auth.create_user(user_id, data.email.lower())
            await conn.execute("UPDATE users SET supabase_migrated=TRUE WHERE id=$1", user_id)
        except Exception as exc:
            logger.error("Supabase Auth provisioning failed for invited admin %s: %s", data.email, exc)

    frontend_url = os.environ.get("FRONTEND_URL", "")
    invite_link = f"{frontend_url}/accept-invite?token={token}"

    try:
        import resend
        resend.api_key = os.environ.get("RESEND_API_KEY", "")
        html = _build_invite_email(data.name.strip(), org["name"], invite_link)
        await asyncio.to_thread(resend.Emails.send, {
            "from": os.environ.get("SENDER_EMAIL", "noreply@notify.1two.one"),
            "to": [data.email.lower()],
            "subject": f"You've been invited to join {org['name']} on 1two.one",
            "html": html,
        })
        logger.info(f"Invite email sent to {data.email}")
    except Exception as e:
        logger.warning(f"Invite email failed (user still created): {e}")
        return {
            "message": "User created but email failed to send — share the link below manually.",
            "invite_link": invite_link,
            "user_id": user_id,
            "email_failed": True,
        }

    return {"message": f"Invitation sent to {data.email}", "user_id": user_id}


@router.get("/ai-usage-report")
async def ai_usage_report(
    org_id: Optional[str] = None,
    provider: Optional[str] = None,
    fallback_only: bool = False,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """Which AI provider (Gemini vs OpenAI) actually served each meeting's
    evidence analysis, and whether it was a fallback — for Super Admin RCA
    on evidence-scan discrepancies. Never surfaced on individual meetings,
    by explicit user request. Only covers analyses run after m030 shipped
    (ai_provider IS NOT NULL) — older rows predate this tracking."""
    _require_super_admin(current_user)
    conditions = ["a.ai_provider IS NOT NULL"]
    params = []
    if org_id:
        params.append(org_id)
        conditions.append(f"a.org_id = ${len(params)}")
    if provider:
        params.append(provider)
        conditions.append(f"a.ai_provider = ${len(params)}")
    if fallback_only:
        conditions.append("a.ai_fallback_used = TRUE")
    if from_date:
        params.append(from_date)
        conditions.append(f"a.created_at >= ${len(params)}")
    if to_date:
        params.append(to_date)
        conditions.append(f"a.created_at <= ${len(params)}")
    where_clause = " AND ".join(conditions)

    async with database.with_admin() as conn:
        items_rows = await conn.fetch(
            f"""SELECT a.id AS analysis_id, a.meeting_id, a.org_id, a.ai_provider, a.ai_fallback_used,
                       a.ai_fallback_reason, a.ai_latency_ms, a.created_at,
                       a.rescanned_at, a.initial_ai_provider, a.initial_ai_fallback_used,
                       a.initial_ai_fallback_reason, a.initial_ai_latency_ms,
                       m.title AS meeting_title, o.name AS org_name
                FROM analyses a
                LEFT JOIN meetings m ON m.id = a.meeting_id
                LEFT JOIN organisations o ON o.id = a.org_id
                WHERE {where_clause}
                ORDER BY a.created_at DESC
                LIMIT 200""",
            *params,
        )
        totals_row = await conn.fetchrow(
            f"""SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE a.ai_fallback_used) AS fallback_count,
                       AVG(a.ai_latency_ms) AS avg_latency_ms
                FROM analyses a WHERE {where_clause}""",
            *params,
        )
        provider_rows = await conn.fetch(
            f"""SELECT a.ai_provider, COUNT(*) AS cnt FROM analyses a WHERE {where_clause}
                GROUP BY a.ai_provider""",
            *params,
        )
        changed_row = await conn.fetchrow(
            f"""SELECT COUNT(*) AS cnt FROM analyses a
                WHERE {where_clause} AND a.rescanned_at IS NOT NULL
                  AND a.initial_ai_provider IS NOT NULL AND a.initial_ai_provider != a.ai_provider""",
            *params,
        )

    total = totals_row["total"] or 0
    fallback_count = totals_row["fallback_count"] or 0
    return {
        "items": [
            {
                "analysis_id": r["analysis_id"],
                "meeting_id": r["meeting_id"],
                "meeting_title": r["meeting_title"],
                "org_id": r["org_id"],
                "org_name": r["org_name"],
                "ai_provider": r["ai_provider"],
                "ai_fallback_used": r["ai_fallback_used"],
                "ai_fallback_reason": r["ai_fallback_reason"],
                "ai_latency_ms": r["ai_latency_ms"],
                "analyzed_at": r["created_at"],
                "rescanned_at": r["rescanned_at"],
                "initial_ai_provider": r["initial_ai_provider"],
                "initial_ai_fallback_used": r["initial_ai_fallback_used"],
                "initial_ai_fallback_reason": r["initial_ai_fallback_reason"],
                "initial_ai_latency_ms": r["initial_ai_latency_ms"],
                "provider_changed_on_rescan": bool(
                    r["rescanned_at"] and r["initial_ai_provider"] and r["ai_provider"]
                    and r["initial_ai_provider"] != r["ai_provider"]
                ),
            }
            for r in items_rows
        ],
        "stats": {
            "total": total,
            "fallback_count": fallback_count,
            "fallback_rate_pct": round((fallback_count / total) * 100, 1) if total else 0,
            "avg_latency_ms": round(float(totals_row["avg_latency_ms"]), 0) if totals_row["avg_latency_ms"] is not None else None,
            "by_provider": {r["ai_provider"]: r["cnt"] for r in provider_rows},
            "provider_changed_on_rescan_count": changed_row["cnt"] or 0,
        },
    }


@router.get("/transcription-usage-report")
async def transcription_usage_report(
    org_id: Optional[str] = None,
    speech_model: Optional[str] = None,
    failed_only: bool = False,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """Which AssemblyAI speech model actually served each meeting's
    transcription, how long it took, and whether it failed — for Super Admin
    to track the transcription pipeline's health separately from the
    Gemini/OpenAI evidence-analysis step above. Covers meetings with a
    completed transcript OR one that failed specifically at the
    transcription stage (m034); older rows predate this tracking and are
    excluded from both categories."""
    _require_super_admin(current_user)
    conditions = ["(t.id IS NOT NULL OR m.failed_stage = 'transcription')"]
    params = []
    if org_id:
        params.append(org_id)
        conditions.append(f"m.org_id = ${len(params)}")
    if speech_model:
        params.append(speech_model)
        conditions.append(f"t.speech_model_used = ${len(params)}")
    if failed_only:
        conditions.append("m.failed_stage = 'transcription'")
    if from_date:
        params.append(from_date)
        conditions.append(f"COALESCE(t.created_at, m.updated_at) >= ${len(params)}")
    if to_date:
        params.append(to_date)
        conditions.append(f"COALESCE(t.created_at, m.updated_at) <= ${len(params)}")
    where_clause = " AND ".join(conditions)

    base_query = f"""FROM meetings m
                LEFT JOIN transcripts t ON t.id = m.transcript_id
                LEFT JOIN organisations o ON o.id = m.org_id
                WHERE {where_clause}"""

    async with database.with_admin() as conn:
        items_rows = await conn.fetch(
            f"""SELECT m.id AS meeting_id, m.title AS meeting_title, m.org_id, o.name AS org_name,
                       m.audio_duration_seconds, m.transcript_has_warnings, m.failed_stage, m.processing_error,
                       t.speech_model_used, t.latency_ms, COALESCE(t.created_at, m.updated_at) AS transcribed_at
                {base_query}
                ORDER BY COALESCE(t.created_at, m.updated_at) DESC
                LIMIT 200""",
            *params,
        )
        totals_row = await conn.fetchrow(
            f"""SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE m.failed_stage = 'transcription') AS failed_count,
                       AVG(t.latency_ms) AS avg_latency_ms,
                       AVG(m.audio_duration_seconds) AS avg_audio_duration_seconds,
                       COUNT(*) FILTER (WHERE m.transcript_has_warnings) AS warnings_count
                {base_query}""",
            *params,
        )
        model_rows = await conn.fetch(
            f"""SELECT t.speech_model_used, COUNT(*) AS cnt {base_query} AND t.speech_model_used IS NOT NULL
                GROUP BY t.speech_model_used""",
            *params,
        )

    total = totals_row["total"] or 0
    failed_count = totals_row["failed_count"] or 0
    return {
        "items": [
            {
                "meeting_id": r["meeting_id"],
                "meeting_title": r["meeting_title"],
                "org_id": r["org_id"],
                "org_name": r["org_name"],
                "audio_duration_seconds": float(r["audio_duration_seconds"]) if r["audio_duration_seconds"] is not None else None,
                "transcript_has_warnings": r["transcript_has_warnings"],
                "failed": r["failed_stage"] == "transcription",
                "processing_error": r["processing_error"] if r["failed_stage"] == "transcription" else None,
                "speech_model_used": r["speech_model_used"],
                "latency_ms": r["latency_ms"],
                "transcribed_at": r["transcribed_at"],
            }
            for r in items_rows
        ],
        "stats": {
            "total": total,
            "failed_count": failed_count,
            "failure_rate_pct": round((failed_count / total) * 100, 1) if total else 0,
            "avg_latency_ms": round(float(totals_row["avg_latency_ms"]), 0) if totals_row["avg_latency_ms"] is not None else None,
            "avg_audio_duration_seconds": round(float(totals_row["avg_audio_duration_seconds"]), 0) if totals_row["avg_audio_duration_seconds"] is not None else None,
            "warnings_count": totals_row["warnings_count"] or 0,
            "by_speech_model": {r["speech_model_used"]: r["cnt"] for r in model_rows},
        },
    }


@router.get("/ai-accuracy-report")
async def ai_accuracy_report(
    org_id: Optional[str] = None,
    action: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    current_user=Depends(get_current_user),
):
    """Global, cross-org view over evidence_feedback (every manager
    accept/reject/flag decision on AI-mapped evidence) — the same data that
    powers each org's own "AI Accuracy" tab in Team Insights, but aggregated
    across all organisations so Super Admin can spot an org (or the whole
    fleet) with an unusually low acceptance rate."""
    _require_super_admin(current_user)
    conditions = ["1=1"]
    params = []
    if org_id:
        params.append(org_id)
        conditions.append(f"ef.org_id = ${len(params)}")
    if action:
        params.append(action)
        conditions.append(f"ef.manager_action = ${len(params)}")
    if from_date:
        params.append(from_date)
        conditions.append(f"ef.timestamp >= ${len(params)}")
    if to_date:
        params.append(to_date)
        conditions.append(f"ef.timestamp <= ${len(params)}")
    where_clause = " AND ".join(conditions)

    async with database.with_admin() as conn:
        items_rows = await conn.fetch(
            f"""SELECT ef.id, ef.meeting_id, ef.upload_id, ef.org_id, ef.user_name, ef.evidence_type,
                       ef.standard_ref, ef.standard_name, ef.ai_confidence, ef.manager_action,
                       ef.timestamp, m.title AS meeting_title, su.label AS upload_label, o.name AS org_name
                FROM evidence_feedback ef
                LEFT JOIN meetings m ON m.id = ef.meeting_id
                LEFT JOIN supervision_uploads su ON su.id = ef.upload_id
                LEFT JOIN organisations o ON o.id = ef.org_id
                WHERE {where_clause}
                ORDER BY ef.timestamp DESC
                LIMIT 200""",
            *params,
        )
        action_rows = await conn.fetch(
            f"""SELECT ef.manager_action, COUNT(*) AS cnt FROM evidence_feedback ef
                WHERE {where_clause} GROUP BY ef.manager_action""",
            *params,
        )
        top_rejected_rows = await conn.fetch(
            f"""SELECT ef.standard_ref, ef.standard_name, COUNT(*) AS cnt FROM evidence_feedback ef
                WHERE {where_clause} AND ef.manager_action = 'rejected'
                GROUP BY ef.standard_ref, ef.standard_name
                ORDER BY cnt DESC LIMIT 10""",
            *params,
        )
        by_org_rows = await conn.fetch(
            f"""SELECT ef.org_id, o.name AS org_name,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE ef.manager_action = 'accepted') AS accepted,
                       COUNT(*) FILTER (WHERE ef.manager_action = 'rejected') AS rejected,
                       COUNT(*) FILTER (WHERE ef.manager_action = 'needs_followup') AS flagged
                FROM evidence_feedback ef
                LEFT JOIN organisations o ON o.id = ef.org_id
                WHERE {where_clause}
                GROUP BY ef.org_id, o.name
                ORDER BY total DESC""",
            *params,
        )

    by_action = {r["manager_action"] or "unknown": r["cnt"] for r in action_rows}
    total = sum(by_action.values())
    accepted = by_action.get("accepted", 0)
    rejected = by_action.get("rejected", 0)
    decided = accepted + rejected
    acceptance_rate = round((accepted / decided) * 100, 1) if decided else None

    by_org = []
    for r in by_org_rows:
        org_decided = (r["accepted"] or 0) + (r["rejected"] or 0)
        by_org.append({
            "org_id": r["org_id"],
            "org_name": r["org_name"] or "Unknown org",
            "total": r["total"],
            "accepted": r["accepted"] or 0,
            "rejected": r["rejected"] or 0,
            "flagged": r["flagged"] or 0,
            "acceptance_rate": round((r["accepted"] / org_decided) * 100, 1) if org_decided else None,
        })

    return {
        "items": [
            {
                "id": r["id"],
                "meeting_id": r["meeting_id"],
                "upload_id": r["upload_id"],
                "source_type": "document" if r["upload_id"] else "meeting",
                "source_label": (r["upload_label"] if r["upload_id"] else r["meeting_title"]) or ("Untitled document" if r["upload_id"] else "Untitled meeting"),
                "meeting_title": r["meeting_title"],
                "org_id": r["org_id"],
                "org_name": r["org_name"],
                "manager_name": r["user_name"],
                "evidence_type": r["evidence_type"],
                "standard_ref": r["standard_ref"],
                "standard_name": r["standard_name"],
                "ai_confidence": r["ai_confidence"],
                "manager_action": r["manager_action"],
                "timestamp": r["timestamp"],
            }
            for r in items_rows
        ],
        "stats": {
            "total": total,
            "by_action": by_action,
            "acceptance_rate": acceptance_rate,
            "top_rejected_standards": [
                {"standard_ref": r["standard_ref"], "standard_name": r["standard_name"], "count": r["cnt"]}
                for r in top_rejected_rows
            ],
        },
        "by_org": by_org,
    }
