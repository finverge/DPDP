"""Outbound webhook delivery engine (FSD Sec. 5.4).

Subscribable events, exactly as scoped in the FSD:
    consent.created, consent.modified, consent.withdrawn,
    data.accessed, breach.detected

Every delivery is HMAC-SHA256 signed (X-ConsentBridge-Signature) so a
receiver can verify a payload actually came from this platform. The first
attempt happens synchronously, inline in the triggering request (capture/
withdraw/masking-apply) — kept to a short timeout so a slow or dead
receiver can't meaningfully stall the caller. A failed attempt is
retried with exponential backoff up to WEBHOOK_MAX_ATTEMPTS; retries
beyond the first happen two ways, both driving the same
process_due_deliveries() below, so neither path is a stub:
  1. an in-process asyncio loop started from main.py's lifespan (real,
     automatic, dev-grade — no queue/worker infra in this environment);
  2. POST /webhooks/deliveries/process-due, callable by a real external
     cron/scheduler in a deployment that has one, or by a human via
     POST /webhooks/deliveries/{id}/retry for one delivery.
A delivery that exhausts every attempt ends at status="failed" — visible
via GET /webhooks/deliveries, never deleted (FSD Sec. 5.4's "not silently
dropped" requirement).

Honest scope note, same discipline as app/ai.py: this is dev-grade
inline+in-process delivery, not a durable outbox/queue. Before production
this belongs behind a real message queue so a delivery attempt can never
be lost to a process restart between "committed as pending" and "sent."
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WebhookDelivery, WebhookDeliveryStatus, WebhookSubscription

logger = logging.getLogger("dpdp.webhooks")

WEBHOOK_EVENT_TYPES = (
    "consent.created",
    "consent.modified",  # fired from PATCH /consents/{id} — duration_days is the only editable field, see routes.py
    "consent.withdrawn",
    "data.accessed",
    "breach.detected",
)

WEBHOOK_MAX_ATTEMPTS = 5
_BACKOFF_SECONDS = [30, 120, 600, 1800, 3600]  # 30s, 2m, 10m, 30m, 1h
_DELIVERY_TIMEOUT_SECONDS = 5.0
_RESPONSE_SNIPPET_LIMIT = 500


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _backoff_for(attempt_count: int) -> int:
    idx = min(attempt_count, len(_BACKOFF_SECONDS)) - 1
    return _BACKOFF_SECONDS[max(idx, 0)]


def enqueue_event(db: Session, *, tenant_id: str, event_type: str, data: dict) -> list[WebhookDelivery]:
    """Called from a route right after the triggering change is committed
    (capture_consent, withdraw_consent, apply_masking, the breach-risk
    check). Fans out to every active subscription for this tenant that
    subscribed to event_type, attempts each one immediately, and always
    returns normally — a delivery failure here must never fail the
    request that triggered it."""
    if event_type not in WEBHOOK_EVENT_TYPES:
        raise ValueError(f"Unknown webhook event_type '{event_type}'.")

    subs = db.execute(
        select(WebhookSubscription).where(
            WebhookSubscription.tenant_id == tenant_id, WebhookSubscription.active.is_(True),
        )
    ).scalars().all()
    subs = [s for s in subs if event_type in s.events]
    if not subs:
        return []

    payload_data = data
    deliveries: list[WebhookDelivery] = []
    for sub in subs:
        delivery = WebhookDelivery(
            subscription_id=sub.id, tenant_id=tenant_id, event_type=event_type,
            payload_json=payload_data, next_attempt_at=_utcnow(),
        )
        db.add(delivery)
        db.flush()  # assign delivery.id before it's referenced in the signed body
        attempt_delivery(delivery, sub)
        deliveries.append(delivery)
    db.commit()
    for d in deliveries:
        db.refresh(d)
    return deliveries


def _build_body(delivery: WebhookDelivery) -> bytes:
    envelope = {
        "event": delivery.event_type,
        "delivery_id": delivery.id,
        "tenant_id": delivery.tenant_id,
        "created_at": delivery.created_at.isoformat() if delivery.created_at else _utcnow().isoformat(),
        "data": delivery.payload_json,
    }
    return json.dumps(envelope, sort_keys=True, default=str).encode("utf-8")


def attempt_delivery(delivery: WebhookDelivery, subscription: WebhookSubscription) -> None:
    """Mutates delivery in place (status/attempt_count/next_attempt_at/
    response_*); the caller commits. Never raises — a network failure is
    just another attempt outcome to record and back off from."""
    body = _build_body(delivery)
    headers = {
        "Content-Type": "application/json",
        "X-ConsentBridge-Event": delivery.event_type,
        "X-ConsentBridge-Delivery-Id": delivery.id,
        "X-ConsentBridge-Signature": _sign(subscription.secret, body),
    }
    delivery.attempt_count += 1
    delivery.last_attempt_at = _utcnow()

    try:
        with httpx.Client(timeout=_DELIVERY_TIMEOUT_SECONDS) as client:
            resp = client.post(subscription.url, content=body, headers=headers)
        delivery.response_status = resp.status_code
        delivery.response_snippet = resp.text[:_RESPONSE_SNIPPET_LIMIT]
        ok = 200 <= resp.status_code < 300
    except httpx.HTTPError as exc:
        delivery.response_status = None
        delivery.response_snippet = f"{type(exc).__name__}: {exc}"[:_RESPONSE_SNIPPET_LIMIT]
        ok = False

    if ok:
        delivery.status = WebhookDeliveryStatus.SUCCESS
        delivery.next_attempt_at = delivery.last_attempt_at
        return

    if delivery.attempt_count >= WEBHOOK_MAX_ATTEMPTS:
        delivery.status = WebhookDeliveryStatus.FAILED
        logger.warning(
            "Webhook delivery %s to %s exhausted %d attempts for event %s.",
            delivery.id, subscription.url, delivery.attempt_count, delivery.event_type,
        )
    else:
        delivery.status = WebhookDeliveryStatus.PENDING
        delivery.next_attempt_at = delivery.last_attempt_at + timedelta(seconds=_backoff_for(delivery.attempt_count))


def process_due_deliveries(db: Session, *, tenant_id: str | None = None, limit: int = 50) -> int:
    """Retries every pending delivery whose backoff has elapsed. Returns
    the number processed. Called by both the in-process background loop
    (main.py) and POST /webhooks/deliveries/process-due."""
    query = select(WebhookDelivery).where(
        WebhookDelivery.status == WebhookDeliveryStatus.PENDING,
        WebhookDelivery.next_attempt_at <= _utcnow(),
    )
    if tenant_id is not None:
        query = query.where(WebhookDelivery.tenant_id == tenant_id)
    due = db.execute(query.order_by(WebhookDelivery.next_attempt_at).limit(limit)).scalars().all()

    processed = 0
    for delivery in due:
        subscription = db.get(WebhookSubscription, delivery.subscription_id)
        if subscription is None or not subscription.active:
            delivery.status = WebhookDeliveryStatus.FAILED
            delivery.response_snippet = "Subscription was deleted or deactivated before this delivery could be retried."
            processed += 1
            continue
        attempt_delivery(delivery, subscription)
        processed += 1
    db.commit()
    return processed
