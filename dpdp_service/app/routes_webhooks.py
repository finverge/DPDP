"""Webhook subscription management + delivery visibility (FSD Sec. 5.4).
Delivery itself lives in app/webhooks.py; this file is the admin surface
tenant staff use to register endpoints and see what was (or wasn't)
delivered — the "failed deliveries are visible on the tenant's compliance
dashboard, not silently dropped" requirement.
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Principal, require_role, require_tenant_match
from app.db import get_session
from app.models import WebhookDelivery, WebhookDeliveryStatus, WebhookSubscription
from app.schemas import (
    WebhookSubscriptionIn, WebhookSubscriptionUpdateIn,
    WebhookSubscriptionOut, WebhookSubscriptionCreatedOut, WebhookDeliveryOut,
)
from app.webhooks import WEBHOOK_EVENT_TYPES, attempt_delivery, process_due_deliveries

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/event-types", response_model=list[str])
def list_event_types():
    return list(WEBHOOK_EVENT_TYPES)


@router.post("/subscriptions", response_model=WebhookSubscriptionCreatedOut)
def create_subscription(
    req: WebhookSubscriptionIn, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "platform_admin")),
):
    require_tenant_match(principal, req.tenant_id)
    secret = secrets.token_hex(24)
    sub = WebhookSubscription(
        tenant_id=req.tenant_id, url=req.url, secret=secret, events=req.events, created_by=req.created_by,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.get("/subscriptions", response_model=list[WebhookSubscriptionOut])
def list_subscriptions(
    tenant_id: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "dpo", "compliance_officer", "platform_admin")),
):
    require_tenant_match(principal, tenant_id)
    return db.execute(
        select(WebhookSubscription).where(WebhookSubscription.tenant_id == tenant_id)
        .order_by(WebhookSubscription.created_at.desc())
    ).scalars().all()


@router.patch("/subscriptions/{subscription_id}", response_model=WebhookSubscriptionOut)
def update_subscription(
    subscription_id: str, req: WebhookSubscriptionUpdateIn, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "platform_admin")),
):
    sub = db.get(WebhookSubscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Webhook subscription not found.")
    require_tenant_match(principal, sub.tenant_id)
    if req.url is not None:
        sub.url = req.url
    if req.events is not None:
        bad = [e for e in req.events if e not in WEBHOOK_EVENT_TYPES]
        if bad:
            raise HTTPException(status_code=422, detail=f"Unknown event type(s) {bad}.")
        sub.events = req.events
    if req.active is not None:
        sub.active = req.active
    db.commit()
    db.refresh(sub)
    return sub


@router.post("/subscriptions/{subscription_id}/rotate-secret", response_model=WebhookSubscriptionCreatedOut)
def rotate_secret(
    subscription_id: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "platform_admin")),
):
    """New secret returned once, same discipline as creation — the old
    secret stops verifying signatures immediately."""
    sub = db.get(WebhookSubscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Webhook subscription not found.")
    require_tenant_match(principal, sub.tenant_id)
    sub.secret = secrets.token_hex(24)
    db.commit()
    db.refresh(sub)
    return sub


@router.delete("/subscriptions/{subscription_id}", status_code=204)
def delete_subscription(
    subscription_id: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "platform_admin")),
):
    sub = db.get(WebhookSubscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Webhook subscription not found.")
    require_tenant_match(principal, sub.tenant_id)
    db.delete(sub)
    db.commit()


@router.get("/deliveries", response_model=list[WebhookDeliveryOut])
def list_deliveries(
    tenant_id: str, status: str | None = None, limit: int = 100, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "dpo", "compliance_officer", "platform_admin")),
):
    require_tenant_match(principal, tenant_id)
    query = select(WebhookDelivery).where(WebhookDelivery.tenant_id == tenant_id)
    if status is not None:
        try:
            query = query.where(WebhookDelivery.status == WebhookDeliveryStatus(status))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Unknown status '{status}'.")
    return db.execute(query.order_by(WebhookDelivery.created_at.desc()).limit(limit)).scalars().all()


@router.post("/deliveries/{delivery_id}/retry", response_model=WebhookDeliveryOut)
def retry_delivery(
    delivery_id: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "platform_admin")),
):
    """Forces an immediate retry regardless of backoff — for a DPO/admin
    who has just fixed the receiving endpoint and doesn't want to wait."""
    delivery = db.get(WebhookDelivery, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Webhook delivery not found.")
    require_tenant_match(principal, delivery.tenant_id)
    if delivery.status == WebhookDeliveryStatus.SUCCESS:
        raise HTTPException(status_code=409, detail="This delivery already succeeded.")
    subscription = db.get(WebhookSubscription, delivery.subscription_id)
    if subscription is None:
        raise HTTPException(status_code=409, detail="The subscription for this delivery no longer exists.")
    attempt_delivery(delivery, subscription)
    db.commit()
    db.refresh(delivery)
    return delivery


@router.post("/deliveries/process-due")
def trigger_process_due(
    db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("platform_admin")),
) -> dict:
    """Maintenance endpoint a real external cron can call in a deployment
    with no in-process scheduler running (see app/webhooks.py module
    docstring). platform_admin-only since it processes every tenant."""
    processed = process_due_deliveries(db)
    return {"processed": processed}
