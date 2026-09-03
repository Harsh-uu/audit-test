"""
Supabase Auth — identity/password backend for this app.

Only credential storage + verification live here. Session issuance (our own
signed JWT + HttpOnly cookies, deps.py::get_current_user, RLS org-scoping via
database.py::with_org) is UNCHANGED and stays entirely our own — this module
is called from inside routers/auth.py's existing endpoints, not a replacement
for them.
"""
import asyncio
import logging
import os
from functools import partial

logger = logging.getLogger(__name__)

_admin_client = None


class SupabaseAuthUnavailable(Exception):
    """Raised when Supabase Auth itself couldn't be reached/errored — distinct
    from a genuine wrong-password response, so callers don't show a misleading
    'Invalid credentials' when the real problem is a transient outage."""


def _get_admin_client():
    """Cached client for stateless admin/service-key REST calls (create_user,
    generate_link, update_user_by_id, get_user_by_id) — safe to share across
    concurrent requests since these never mutate a 'current session' on the
    client object."""
    global _admin_client
    if _admin_client is not None:
        return _admin_client
    from supabase import create_client
    _admin_client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    return _admin_client


def _sync_create_user(user_id: str, email: str):
    """Create the Supabase Auth identity for an existing/new app user, with no
    usable password yet — they activate via a recovery link (forced reset /
    invite). Idempotent: if the id or email already exists, treat as already
    migrated rather than erroring."""
    from supabase_auth.types import AdminUserAttributes
    client = _get_admin_client()
    try:
        return client.auth.admin.create_user(AdminUserAttributes(
            id=user_id, email=email, email_confirm=True,
        ))
    except Exception as exc:
        msg = str(exc).lower()
        if "already been registered" in msg or "already exists" in msg or "email_exists" in msg:
            logger.info("Supabase Auth: user %s already provisioned, skipping", email)
            return None
        logger.error("Supabase Auth: create_user failed for %s: %s", email, exc, exc_info=True)
        raise


def _sync_generate_recovery_link(email: str) -> str:
    from supabase_auth.types import GenerateLinkParams
    client = _get_admin_client()
    resp = client.auth.admin.generate_link(GenerateLinkParams(type="recovery", email=email))
    return resp.properties.action_link


def _sync_set_password(user_id: str, new_password: str):
    from supabase_auth.types import AdminUserAttributes
    client = _get_admin_client()
    return client.auth.admin.update_user_by_id(user_id, AdminUserAttributes(password=new_password))


def _sync_user_exists(user_id: str) -> bool:
    client = _get_admin_client()
    try:
        resp = client.auth.admin.get_user_by_id(user_id)
        return resp is not None and resp.user is not None
    except Exception:
        return False


async def create_user(user_id: str, email: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_sync_create_user, user_id, email))


async def verify_login(email: str, password: str) -> bool:
    """Verify credentials directly against Supabase Auth's token endpoint via
    a stateless HTTP call — measured consistently under ~0.4s and avoids any
    shared-client session state, vs the SDK's sign_in_with_password which
    showed intermittent multi-second latency/timeouts in testing."""
    import httpx
    url = f"{os.environ['SUPABASE_URL']}/auth/v1/token?grant_type=password"
    headers = {"apikey": os.environ["SUPABASE_SERVICE_KEY"], "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json={"email": email, "password": password})
    except httpx.HTTPError as exc:
        logger.error("Supabase Auth: sign-in request failed for %s: %s", email, exc)
        raise SupabaseAuthUnavailable(str(exc)) from exc
    if resp.status_code == 200:
        return True
    if resp.status_code == 429 or resp.status_code == 403:
        # Rate limit / config error from Supabase itself — not a real "wrong
        # password" outcome, so don't tell the user that and don't let it
        # count against our own login lockout counter.
        logger.error("Supabase Auth: sign-in blocked (status=%s) for %s: %s", resp.status_code, email, resp.text)
        raise SupabaseAuthUnavailable(f"status {resp.status_code}")
    if resp.status_code < 500:
        return False  # genuinely wrong credentials / unconfirmed / etc.
    logger.error("Supabase Auth: sign-in server error for %s: status=%s body=%s", email, resp.status_code, resp.text)
    raise SupabaseAuthUnavailable(f"status {resp.status_code}")


async def generate_recovery_link(email: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_sync_generate_recovery_link, email))


async def set_password(user_id: str, new_password: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_sync_set_password, user_id, new_password))


async def user_exists(user_id: str) -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_sync_user_exists, user_id))
