"""Transactional emails for the Stripe self-serve billing lifecycle —
payment-failed notices to org admins, founding-price month-11 reminders,
and Super Admin alerts (abandoned signups, stuck provisioning, canceled
subscriptions). Same best-effort Resend pattern as
utils/org_provisioning.py's invite email — never raises.
"""
import os
import asyncio
import logging

logger = logging.getLogger(__name__)


async def _send(to_email: str, subject: str, html_body: str) -> bool:
    if not to_email:
        return False
    try:
        import resend
        resend.api_key = os.environ.get("RESEND_API_KEY", "")
        await asyncio.to_thread(resend.Emails.send, {
            "from": os.environ.get("SENDER_EMAIL", "noreply@notify.1two.one"),
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        })
        return True
    except Exception as e:
        logger.warning("Billing email to %s failed: %s", to_email, e)
        return False


async def send_payment_failed_email(admin_email: str, admin_name: str, org_name: str) -> bool:
    body = (
        f"<p>Hi {admin_name or 'there'},</p>"
        f"<p>We were unable to process the latest payment for <strong>{org_name}</strong>'s 1two.one subscription. "
        "Please check your card details to avoid any interruption to your account.</p>"
    )
    return await _send(admin_email, f"Payment failed for {org_name} on 1two.one", body)


async def send_founding_reminder_email(admin_email: str, admin_name: str, org_name: str, tier: str, lock_until) -> bool:
    date_str = lock_until.strftime("%d %B %Y") if hasattr(lock_until, "strftime") else str(lock_until)
    body = (
        f"<p>Hi {admin_name or 'there'},</p>"
        f"<p>As a valued founding member, your {tier.title()} plan price for <strong>{org_name}</strong> increases to the "
        f"regular rate on <strong>{date_str}</strong>. No action is needed — your subscription will continue automatically.</p>"
    )
    return await _send(admin_email, f"Your founding price changes on {date_str}", body)


async def notify_super_admin(text: str) -> bool:
    super_admin_email = os.environ.get("SUPER_ADMIN_EMAIL", "")
    if not super_admin_email:
        logger.warning("SUPER_ADMIN_EMAIL not set — cannot send alert: %s", text)
        return False
    return await _send(super_admin_email, "1two.one billing alert", f"<pre>{text}</pre>")
