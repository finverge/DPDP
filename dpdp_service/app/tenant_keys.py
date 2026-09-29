"""Tenant API-key lifecycle: hashed storage, one-time reveal, manual and
scheduled-automatic rotation with a grace period.

Honest scope note: no route in this service currently verifies a
presented api_key against anything (routes_tenants.py's api_key has
always been generated but never enforced — a pre-existing gap, not
introduced here). verify_api_key() below is real and tested, ready for
whichever future route actually gates on one; this file makes the key's
*lifecycle* real (hashed at rest, rotatable, time-bounded) without
inventing new authentication middleware nobody asked for.

There is no email/SMS infrastructure anywhere in this platform, so the
"notification" half of scheduled rotation is passive, not a push: a
rotated tenant's new api_key_rotate_by and the old key's
previous_api_key_expires_at are simply visible via GET /tenants/{id},
the same "surface it, don't fake sending it" discipline as everywhere
else "not yet built" is handled honestly in this codebase.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tenant
from app.security import hash_password, verify_password

API_KEY_ROTATION_INTERVAL_DAYS = 90
API_KEY_GRACE_PERIOD_HOURS = 48
_PREFIX_LENGTH = 16  # "cb_live_" (8) + 8 chars of the random token — enough to recognize, not enough to guess


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite doesn't reliably round-trip tzinfo through DateTime(timezone=True)
    (same issue fixed once already in routes_auth.py) — normalize before
    comparing against a tz-aware _utcnow()."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _generate_plain_key() -> str:
    return "cb_live_" + secrets.token_urlsafe(24)


def issue_api_key(tenant: Tenant) -> str:
    """Sets a brand-new key on a Tenant with no prior key (creation only —
    rotate_api_key is what a real rotation calls). Returns the plaintext,
    which the caller must return to the client now: it is never stored
    and can never be recovered after this call returns."""
    plain = _generate_plain_key()
    tenant.api_key_hash = hash_password(plain)
    tenant.api_key_prefix = plain[:_PREFIX_LENGTH]
    tenant.api_key_created_at = _utcnow()
    tenant.api_key_rotate_by = _utcnow() + timedelta(days=API_KEY_ROTATION_INTERVAL_DAYS)
    tenant.previous_api_key_hash = None
    tenant.previous_api_key_expires_at = None
    return plain


def rotate_api_key(tenant: Tenant, *, grace_hours: int = API_KEY_GRACE_PERIOD_HOURS) -> str:
    """Issues a new key, keeping the outgoing one valid for `grace_hours`
    so an in-flight integration isn't broken the instant this call
    returns. Used by both the manual rotate endpoint and the scheduled
    automatic-rotation loop below — the two are the same operation with
    different triggers, not two different code paths to keep in sync."""
    plain = _generate_plain_key()
    tenant.previous_api_key_hash = tenant.api_key_hash
    tenant.previous_api_key_expires_at = _utcnow() + timedelta(hours=grace_hours)
    tenant.api_key_hash = hash_password(plain)
    tenant.api_key_prefix = plain[:_PREFIX_LENGTH]
    tenant.api_key_created_at = _utcnow()
    tenant.api_key_rotate_by = _utcnow() + timedelta(days=API_KEY_ROTATION_INTERVAL_DAYS)
    return plain


def verify_api_key(tenant: Tenant, presented_key: str) -> bool:
    """True if presented_key matches the current key, or the previous key
    within its grace window. Not called by any route today (see module
    docstring) — exercised directly by tests so it's correct and ready."""
    if verify_password(presented_key, tenant.api_key_hash):
        return True
    if (
        tenant.previous_api_key_hash is not None
        and tenant.previous_api_key_expires_at is not None
        and _aware(tenant.previous_api_key_expires_at) > _utcnow()
        and verify_password(presented_key, tenant.previous_api_key_hash)
    ):
        return True
    return False


def process_due_rotations(db: Session, *, limit: int = 50) -> int:
    """Force-rotates every tenant whose api_key_rotate_by has passed.
    Called by both the in-process background loop (main.py) and
    POST /tenants/rotate-due-api-keys, the same "real loop + cron-callable
    maintenance endpoint" pattern as webhooks/regulatory-watch."""
    due = db.execute(
        select(Tenant).where(Tenant.api_key_rotate_by <= _utcnow()).limit(limit)
    ).scalars().all()
    for tenant in due:
        rotate_api_key(tenant)
    if due:
        db.commit()
    return len(due)
