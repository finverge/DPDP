"""API routes — Consent Management Engine (FSD Sec. 3) + Grievance/DPO
module (FSD Sec. 8.3). Every query filters on tenant_id explicitly (see
models.py tenancy note) — no route here ever answers across tenants.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import breach_risk_score, check_drift
from app.auth import Principal, require_role, require_tenant_match
from app.db import get_session
from app.masking import apply_policy
from app.models import (
    Notice, NoticeStatus, ConsentRecord, ConsentAuditEvent, ConsentAuditEventType,
    Grievance, GrievanceStatus, DPOContact, MaskingPolicy, MaskingAuditEvent, UsageEvent,
    WebhookDelivery, WebhookDeliveryStatus,
)
from app.schemas import (
    NoticeDraftIn, NoticeOut, NoticeApproveIn,
    ConsentCaptureIn, ConsentRecordOut, ConsentWithdrawIn, ConsentModifyIn, ConsentAuditEventOut,
    GrievanceCreateIn, GrievanceOut, GrievanceResolveIn, GrievanceFlagFrivolousIn,
    DPOContactIn, DPOContactOut,
    MaskingPolicyIn, MaskingPolicyOut, MaskingApplyIn, MaskingApplyOut,
)
from app.webhooks import enqueue_event

router = APIRouter(tags=["dpdp-consent-platform"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------- #
# Notices
# ---------------------------------------------------------------------- #
@router.post("/notices", response_model=NoticeOut)
def draft_notice(
    req: NoticeDraftIn, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "dpo", "platform_admin")),
):
    """Creates a new draft notice version. Never overwrites a prior
    version — Notice is append-only (models.py docstring); a tenant admin
    (or the AI Notice Generator, BRD Sec. 6.1) drafts here, a DPO approves
    via /notices/{id}/approve before it is ever shown to a Data Principal."""
    require_tenant_match(principal, req.tenant_id)
    last = db.execute(
        select(Notice)
        .where(Notice.tenant_id == req.tenant_id, Notice.language == req.language)
        .order_by(Notice.version.desc())
    ).scalars().first()
    next_version = (last.version + 1) if last else 1
    notice = Notice(tenant_id=req.tenant_id, language=req.language, content=req.content, version=next_version)
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return notice


@router.post("/notices/{notice_id}/approve", response_model=NoticeOut)
def approve_notice(
    notice_id: str, req: NoticeApproveIn, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("dpo", "tenant_admin", "platform_admin")),
):
    """DPO approval checkpoint (FSD Sec. 3.1, BRD Sec. 6.9 human-in-the-
    loop discipline). Retires the tenant/language's previously approved
    notice so exactly one is ever live at a time."""
    notice = db.get(Notice, notice_id)
    if notice is None:
        raise HTTPException(status_code=404, detail="Notice not found.")
    require_tenant_match(principal, notice.tenant_id)
    if notice.status == NoticeStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Notice is already approved.")

    previously_approved = db.execute(
        select(Notice).where(
            Notice.tenant_id == notice.tenant_id,
            Notice.language == notice.language,
            Notice.status == NoticeStatus.APPROVED,
        )
    ).scalars().first()
    if previously_approved is not None:
        previously_approved.status = NoticeStatus.RETIRED

    notice.status = NoticeStatus.APPROVED
    notice.approved_by = req.approved_by
    notice.approved_at = _utcnow()
    db.commit()
    db.refresh(notice)
    return notice


@router.get("/notices/current", response_model=NoticeOut)
def get_current_notice(tenant_id: str, language: str = "en", db: Session = Depends(get_session)):
    """The notice a consent-capture widget must render before requesting
    any grant (§5). Returns 404 rather than a blank/default notice if the
    tenant has never approved one — a Data Fiduciary with no approved
    notice must find out loudly, not silently let capture proceed with
    nothing shown (FSD Sec. 3.1)."""
    notice = db.execute(
        select(Notice).where(
            Notice.tenant_id == tenant_id, Notice.language == language, Notice.status == NoticeStatus.APPROVED,
        )
    ).scalars().first()
    if notice is None:
        raise HTTPException(
            status_code=404,
            detail=f"No approved notice for tenant '{tenant_id}' in language '{language}'. "
                   f"A DPO must approve one via POST /notices/{{id}}/approve before consent can be captured.",
        )
    return notice


# ---------------------------------------------------------------------- #
# Consent
# ---------------------------------------------------------------------- #
@router.post("/consents/capture", response_model=list[ConsentRecordOut])
def capture_consent(req: ConsentCaptureIn, db: Session = Depends(get_session)):
    """Granular capture (FSD Sec. 3.2) — one ConsentRecord per grant, never
    a single bundled row. Rejects a notice_id that doesn't belong to the
    tenant or isn't approved, so a capture can never reference a notice
    the Data Principal was never actually shown."""
    notice = db.get(Notice, req.notice_id)
    if notice is None or notice.tenant_id != req.tenant_id:
        raise HTTPException(status_code=404, detail="Notice not found for this tenant.")
    if notice.status != NoticeStatus.APPROVED:
        raise HTTPException(status_code=422, detail="Cannot capture consent against a notice that is not approved.")

    created: list[ConsentRecord] = []
    for grant in req.grants:
        record = ConsentRecord(
            tenant_id=req.tenant_id,
            data_principal_id=req.data_principal_id,
            notice_id=req.notice_id,
            language=req.language,
            data_category=grant.data_category,
            purpose=grant.purpose,
            duration_days=grant.duration_days,
        )
        db.add(record)
        db.flush()  # assign record.id before the audit event references it
        db.add(ConsentAuditEvent(
            consent_record_id=record.id,
            event_type=ConsentAuditEventType.CAPTURED,
            actor=req.data_principal_id,
            detail=f"Granted for purpose '{grant.purpose}' against notice v{notice.version} ({req.language}).",
        ))
        created.append(record)

    db.add(UsageEvent(tenant_id=req.tenant_id, event_type="consent.capture"))
    db.commit()
    for r in created:
        db.refresh(r)

    # FSD Sec. 5.4 — one consent.created event per grant, matching the
    # "one ConsentRecord per grant" discipline above (never one bundled event).
    for r in created:
        enqueue_event(db, tenant_id=req.tenant_id, event_type="consent.created", data={
            "consent_record_id": r.id, "data_principal_id": r.data_principal_id,
            "data_category": r.data_category, "purpose": r.purpose,
            "notice_id": r.notice_id, "language": r.language,
        })
    return created


@router.post("/consents/{consent_id}/withdraw", response_model=ConsentRecordOut)
def withdraw_consent(consent_id: str, req: ConsentWithdrawIn, db: Session = Depends(get_session)):
    """Withdrawal (FSD Sec. 3.3) — as easy as granting: one call, one
    purpose, independent of every other grant this Data Principal holds
    (§6(4)-(6)). Idempotency guard: withdrawing twice is a 409, not a
    silent no-op, so a caller can tell the difference between "it worked"
    and "it was already done"."""
    record = db.get(ConsentRecord, consent_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Consent record not found.")
    if record.withdrawn_at is not None:
        raise HTTPException(status_code=409, detail="This consent was already withdrawn.")

    record.withdrawn_at = _utcnow()
    db.add(ConsentAuditEvent(
        consent_record_id=record.id,
        event_type=ConsentAuditEventType.WITHDRAWN,
        actor=req.actor,
        detail=req.reason,
    ))
    db.commit()
    db.refresh(record)

    # FSD Sec. 5.4 — "withdrawal triggers a propagation event (Module 3
    # webhook) to every Processor subscribed to that consent record."
    enqueue_event(db, tenant_id=record.tenant_id, event_type="consent.withdrawn", data={
        "consent_record_id": record.id, "data_principal_id": record.data_principal_id,
        "data_category": record.data_category, "purpose": record.purpose,
        "actor": req.actor, "reason": req.reason,
    })
    return record


@router.patch("/consents/{consent_id}", response_model=ConsentRecordOut)
def modify_consent(consent_id: str, req: ConsentModifyIn, db: Session = Depends(get_session)):
    """The only supported "modification" of a grant: its retention
    duration (schemas.ConsentModifyIn docstring explains why purpose/
    data_category can't move here). Left open like capture/withdraw — a
    Data Principal renewing or shortening their own grant's duration
    needs no tenant-staff auth, same as withdrawing it (FSD Sec. 3.3).
    Backs the consent.modified webhook event (FSD Sec. 5.4) that had no
    trigger before this endpoint existed."""
    record = db.get(ConsentRecord, consent_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Consent record not found.")
    if record.withdrawn_at is not None:
        raise HTTPException(status_code=409, detail="Cannot modify a withdrawn consent record.")

    previous_duration = record.duration_days
    record.duration_days = req.duration_days
    db.add(ConsentAuditEvent(
        consent_record_id=record.id,
        event_type=ConsentAuditEventType.MODIFIED,
        actor=req.actor,
        detail=f"duration_days changed from {previous_duration!r} to {req.duration_days!r}."
               + (f" Reason: {req.reason}" if req.reason else ""),
    ))
    db.commit()
    db.refresh(record)

    enqueue_event(db, tenant_id=record.tenant_id, event_type="consent.modified", data={
        "consent_record_id": record.id, "data_principal_id": record.data_principal_id,
        "data_category": record.data_category, "purpose": record.purpose,
        "previous_duration_days": previous_duration, "duration_days": record.duration_days,
        "actor": req.actor, "reason": req.reason,
    })
    return record


@router.get("/consents", response_model=list[ConsentRecordOut])
def list_consents(tenant_id: str, data_principal_id: str, db: Session = Depends(get_session)):
    """The consent vault view (FSD Sec. 3, Module 1) — every grant, active
    or withdrawn, for one Data Principal at one tenant. This is what a
    Rights Portal / SDK widget renders as "your permissions"."""
    return db.execute(
        select(ConsentRecord)
        .where(ConsentRecord.tenant_id == tenant_id, ConsentRecord.data_principal_id == data_principal_id)
        .order_by(ConsentRecord.granted_at.desc())
    ).scalars().all()


@router.get("/consents/{consent_id}/audit", response_model=list[ConsentAuditEventOut])
def get_consent_audit(consent_id: str, db: Session = Depends(get_session)):
    """The §6(10) burden-of-proof endpoint — full notice-plus-consent
    trail for one grant, on demand from the tenant, the Board, or a
    proceeding (FSD Sec. 3.4)."""
    record = db.get(ConsentRecord, consent_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Consent record not found.")
    return db.execute(
        select(ConsentAuditEvent)
        .where(ConsentAuditEvent.consent_record_id == consent_id)
        .order_by(ConsentAuditEvent.created_at)
    ).scalars().all()


# ---------------------------------------------------------------------- #
# Data Minimization & Masking (FSD Sec. 4, BRD P360-04/05)
# ---------------------------------------------------------------------- #
@router.put("/masking/policies", response_model=MaskingPolicyOut)
def upsert_masking_policy(
    req: MaskingPolicyIn, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "platform_admin")),
):
    """Upsert, keyed on (tenant_id, purpose) — one policy per purpose,
    authored per-purpose not as a blanket per-tenant switch (FSD Sec.
    4.1)."""
    require_tenant_match(principal, req.tenant_id)
    existing = db.execute(
        select(MaskingPolicy).where(MaskingPolicy.tenant_id == req.tenant_id, MaskingPolicy.purpose == req.purpose)
    ).scalars().first()
    if existing is None:
        existing = MaskingPolicy(
            tenant_id=req.tenant_id, purpose=req.purpose, field_rules=req.field_rules, created_by=req.created_by,
        )
        db.add(existing)
    else:
        existing.field_rules = req.field_rules
        existing.created_by = req.created_by
    db.commit()
    db.refresh(existing)
    return existing


@router.get("/masking/policies", response_model=list[MaskingPolicyOut])
def list_masking_policies(tenant_id: str, db: Session = Depends(get_session)):
    return db.execute(select(MaskingPolicy).where(MaskingPolicy.tenant_id == tenant_id)).scalars().all()


@router.post("/masking/apply", response_model=MaskingApplyOut)
def apply_masking(req: MaskingApplyIn, db: Session = Depends(get_session)):
    """The runtime gate (FSD Sec. 4.2): any onward data share for a
    declared purpose passes through here. Fail-closed — a purpose with no
    configured policy is a 422, not a pass-through of unmasked data. Every
    call is logged, success or block (FSD Sec. 4.3), which is the primary
    reason this is a real HTTP call from a caller like Fraud360 rather
    than a masking function each caller reimplements locally: one shared
    audit trail instead of N per-caller ones."""
    policy = db.execute(
        select(MaskingPolicy).where(MaskingPolicy.tenant_id == req.tenant_id, MaskingPolicy.purpose == req.purpose)
    ).scalars().first()

    fields_in = sum(len(r) for r in req.records)

    if policy is None:
        db.add(MaskingAuditEvent(
            tenant_id=req.tenant_id, purpose=req.purpose, actor=req.actor, outcome="blocked_no_policy",
            fields_in=fields_in, fields_out=0,
            detail=f"No masking policy configured for purpose '{req.purpose}'.",
        ))
        db.commit()
        raise HTTPException(
            status_code=422,
            detail=f"No masking policy configured for tenant '{req.tenant_id}' / purpose '{req.purpose}'. "
                   f"Configure one via PUT /masking/policies before this data can be shared for this purpose.",
        )

    masked = [apply_policy(r, policy.field_rules) for r in req.records]
    fields_out = sum(len(r) for r in masked)

    db.add(MaskingAuditEvent(
        tenant_id=req.tenant_id, purpose=req.purpose, actor=req.actor, outcome="applied",
        fields_in=fields_in, fields_out=fields_out,
        detail=f"Applied policy against {len(req.records)} record(s).",
    ))
    # BRD Sec. 6.2 / P360-18 — only when the caller scoped this call to one
    # Data Principal (schemas.MaskingApplyIn's data_principal_id docstring
    # explains why bulk/legitimate-use callers like Fraud360 correctly omit it).
    new_drift_flag = None
    if req.data_principal_id:
        new_drift_flag = check_drift(db, tenant_id=req.tenant_id, data_principal_id=req.data_principal_id,
                                      purpose=req.purpose, actor=req.actor)
    db.add(UsageEvent(tenant_id=req.tenant_id, event_type="masking.apply"))
    db.commit()

    # FSD Sec. 5.4 — every successful onward data share ("export, API
    # response, partner webhook payload" per Sec. 4.2) is a data.accessed event.
    enqueue_event(db, tenant_id=req.tenant_id, event_type="data.accessed", data={
        "purpose": req.purpose, "actor": req.actor, "record_count": len(req.records),
        "data_principal_id": req.data_principal_id,
    })

    # FSD Sec. 5.4 breach.detected — fired the moment a fresh drift flag
    # actually pushes the tenant into the "high" breach-risk band, not on
    # every call once it's already there: a 24h cooldown (one existing
    # breach.detected delivery for this tenant in that window) stops the
    # same detection from re-firing on every subsequent masking/apply call.
    if new_drift_flag is not None:
        risk = breach_risk_score(db, tenant_id=req.tenant_id)
        if risk["band"] == "high":
            cooldown_since = _utcnow() - timedelta(hours=24)
            recent_alert = db.execute(
                select(WebhookDelivery).where(
                    WebhookDelivery.tenant_id == req.tenant_id,
                    WebhookDelivery.event_type == "breach.detected",
                    WebhookDelivery.status != WebhookDeliveryStatus.FAILED,
                    WebhookDelivery.created_at >= cooldown_since,
                )
            ).scalars().first()
            if recent_alert is None:
                enqueue_event(db, tenant_id=req.tenant_id, event_type="breach.detected", data=risk)

    return MaskingApplyOut(outcome="applied", records=masked, fields_in=fields_in, fields_out=fields_out)


# ---------------------------------------------------------------------- #
# Grievance (BRD P360-11)
# ---------------------------------------------------------------------- #
@router.post("/grievances", response_model=GrievanceOut)
def create_grievance(req: GrievanceCreateIn, db: Session = Depends(get_session)):
    grievance = Grievance(
        tenant_id=req.tenant_id, data_principal_id=req.data_principal_id,
        category=req.category, subject=req.subject, description=req.description,
    )
    db.add(grievance)
    db.add(UsageEvent(tenant_id=req.tenant_id, event_type="grievance.create"))
    db.commit()
    db.refresh(grievance)
    return grievance


@router.get("/grievances", response_model=list[GrievanceOut])
def list_grievances(
    tenant_id: str, status: str | None = None, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "dpo", "compliance_officer", "platform_admin")),
):
    require_tenant_match(principal, tenant_id)
    query = select(Grievance).where(Grievance.tenant_id == tenant_id)
    if status is not None:
        try:
            query = query.where(Grievance.status == GrievanceStatus(status))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Unknown status '{status}'.")
    return db.execute(query.order_by(Grievance.created_at.desc())).scalars().all()


@router.get("/grievances/{grievance_id}", response_model=GrievanceOut)
def get_grievance(
    grievance_id: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "dpo", "compliance_officer", "platform_admin")),
):
    grievance = db.get(Grievance, grievance_id)
    if grievance is None:
        raise HTTPException(status_code=404, detail="Grievance not found.")
    require_tenant_match(principal, grievance.tenant_id)
    return grievance


@router.post("/grievances/{grievance_id}/resolve", response_model=GrievanceOut)
def resolve_grievance(
    grievance_id: str, req: GrievanceResolveIn, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "compliance_officer", "platform_admin")),
):
    grievance = db.get(Grievance, grievance_id)
    if grievance is None:
        raise HTTPException(status_code=404, detail="Grievance not found.")
    require_tenant_match(principal, grievance.tenant_id)
    if grievance.status in (GrievanceStatus.RESOLVED, GrievanceStatus.REJECTED):
        raise HTTPException(status_code=409, detail=f"Grievance is already {grievance.status.value}.")
    grievance.status = GrievanceStatus.RESOLVED
    grievance.resolved_at = _utcnow()
    grievance.resolved_by = req.resolved_by
    grievance.resolution_note = req.resolution_note
    db.commit()
    db.refresh(grievance)
    return grievance


@router.post("/grievances/{grievance_id}/flag-frivolous", response_model=GrievanceOut)
def flag_frivolous(
    grievance_id: str, req: GrievanceFlagFrivolousIn, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "compliance_officer", "platform_admin")),
):
    """§15(d) / §28(12) — a Compliance Officer's determination, never
    automated (BRD Sec. 6.8's Grievance Triage Assistant may flag a
    *candidate*, but only a human role calls this endpoint)."""
    grievance = db.get(Grievance, grievance_id)
    if grievance is None:
        raise HTTPException(status_code=404, detail="Grievance not found.")
    require_tenant_match(principal, grievance.tenant_id)
    grievance.is_frivolous = True
    grievance.status = GrievanceStatus.REJECTED
    grievance.resolved_at = _utcnow()
    grievance.resolved_by = req.flagged_by
    grievance.resolution_note = req.note or "Flagged as false/frivolous."
    db.commit()
    db.refresh(grievance)
    return grievance


# ---------------------------------------------------------------------- #
# DPO contact (§8(9)-(10))
# ---------------------------------------------------------------------- #
@router.put("/dpo-contact", response_model=DPOContactOut)
def upsert_dpo_contact(
    req: DPOContactIn, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "platform_admin")),
):
    require_tenant_match(principal, req.tenant_id)
    existing = db.get(DPOContact, req.tenant_id)
    if existing is None:
        existing = DPOContact(tenant_id=req.tenant_id, name=req.name, email=req.email, phone=req.phone)
        db.add(existing)
    else:
        existing.name = req.name
        existing.email = req.email
        existing.phone = req.phone
    db.commit()
    db.refresh(existing)
    return existing


@router.get("/dpo-contact", response_model=DPOContactOut)
def get_dpo_contact(tenant_id: str, db: Session = Depends(get_session)):
    contact = db.get(DPOContact, tenant_id)
    if contact is None:
        raise HTTPException(status_code=404, detail=f"No DPO/grievance contact published yet for tenant '{tenant_id}'.")
    return contact
