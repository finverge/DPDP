"""Phase 2 (BRD Sec. 12) — External SaaS launch: multi-tenant self-service
onboarding, white-label branding, usage metering.

Billing itself (charging a card, invoicing) is deliberately not built
here — this service tracks usage (UsageEvent, model.py) as the data layer
a real billing system would meter against, but never touches a payment
method. That boundary is intentional, not a gap: collecting/processing
payment details is out of scope for what a Claude session should do
unattended, and more practically, real billing needs a real payment
processor decision (BRD Sec. 14 open questions) this file shouldn't make
unilaterally.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import Principal, require_role, require_tenant_match
from app.db import get_session
from app.models import Tenant, UsageEvent
from app.schemas import TenantCreateIn, TenantOut, TenantCreatedOut, TenantBrandingIn, TenantUsageOut
from app.tenant_keys import issue_api_key, process_due_rotations, rotate_api_key

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", response_model=TenantCreatedOut)
def create_tenant(req: TenantCreateIn, db: Session = Depends(get_session)):
    """Self-service onboarding (FSD Sec. 5.1) — a new tenant gets an
    isolated namespace and an API key immediately; it still needs its own
    approved notice(s) and masking policies configured before consent
    capture / masking will actually work (the same fail-closed rules
    Phase 1 already enforces apply unchanged to every tenant, seeded or not).
    The response carries the plaintext key once (app/tenant_keys.py) —
    it is hashed before this function returns and can never be shown again."""
    tenant = Tenant(name=req.name, plan=req.plan)
    plain_key = issue_api_key(tenant)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return TenantCreatedOut(**TenantOut.model_validate(tenant).model_dump(), api_key=plain_key)


@router.get("/{tenant_id}", response_model=TenantOut)
def get_tenant(tenant_id: str, db: Session = Depends(get_session)):
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return tenant


@router.post("/{tenant_id}/rotate-api-key", response_model=TenantCreatedOut)
def rotate_tenant_api_key(
    tenant_id: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "platform_admin")),
):
    """On-demand rotation (app/tenant_keys.py) — the outgoing key keeps
    working for a grace window so an in-flight integration isn't broken
    the instant this returns. Same trigger as the scheduled automatic
    rotation below, just fired by a human instead of the clock."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    require_tenant_match(principal, tenant_id)
    plain_key = rotate_api_key(tenant)
    db.commit()
    db.refresh(tenant)
    return TenantCreatedOut(**TenantOut.model_validate(tenant).model_dump(), api_key=plain_key)


@router.post("/rotate-due-api-keys")
def trigger_due_rotations(
    db: Session = Depends(get_session), principal: Principal = Depends(require_role("platform_admin")),
) -> dict:
    """Maintenance endpoint a real external cron can call in a deployment
    with no in-process scheduler running (main.py), mirroring
    POST /webhooks/deliveries/process-due and POST /regulatory-watch/
    check-all. platform_admin-only since it rotates keys across every tenant."""
    rotated = process_due_rotations(db)
    return {"rotated": rotated}


@router.put("/{tenant_id}/branding", response_model=TenantOut)
def update_branding(
    tenant_id: str, req: TenantBrandingIn, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "platform_admin")),
):
    """White-label theming (BRD Sec. 8 business model) — these three
    fields map 1:1 to the SDK widget's `theme` config object
    (sdk/dpdp-consent-widget.js), so a tenant configured here can drive
    the widget via GET /tenants/{id}/branding instead of hand-authoring
    a theme object in their own integration code."""
    require_tenant_match(principal, tenant_id)
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    if req.brand_primary_color is not None:
        tenant.brand_primary_color = req.brand_primary_color
    if req.brand_logo_url is not None:
        tenant.brand_logo_url = req.brand_logo_url
    if req.brand_font_family is not None:
        tenant.brand_font_family = req.brand_font_family
    db.commit()
    db.refresh(tenant)
    return tenant


@router.get("/{tenant_id}/usage", response_model=TenantUsageOut)
def get_usage(
    tenant_id: str, window_days: int = 30, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "platform_admin")),
):
    """The metering data a real billing system (Stripe or otherwise —
    not this service's job) would read to compute an invoice."""
    require_tenant_match(principal, tenant_id)
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = db.execute(
        select(UsageEvent.event_type, func.count(UsageEvent.id))
        .where(UsageEvent.tenant_id == tenant_id, UsageEvent.created_at >= since)
        .group_by(UsageEvent.event_type)
    ).all()
    return TenantUsageOut(tenant_id=tenant_id, window_days=window_days, counts={k: v for k, v in rows})
