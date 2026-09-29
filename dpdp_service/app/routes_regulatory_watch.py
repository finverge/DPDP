"""Regulatory-Change Watch Agent admin surface (BRD Sec. 6.6). Platform-
level, not tenant-scoped (see app/regulatory_watch.py) — curating watched
sources and acknowledging alerts is platform_admin-only (Finverge staff),
but any authenticated staff role can view sources/alerts since a
regulatory change is relevant to every tenant's compliance posture.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Principal, require_role
from app.db import get_session
from app.models import RegulatoryWatchAlert, RegulatoryWatchAlertStatus, RegulatoryWatchSource
from app.regulatory_watch import check_all_sources, check_source
from app.schemas import (
    RegulatoryWatchSourceIn, RegulatoryWatchSourceUpdateIn, RegulatoryWatchSourceOut,
    RegulatoryWatchAlertOut, RegulatoryWatchAcknowledgeIn,
)

router = APIRouter(prefix="/regulatory-watch", tags=["regulatory-watch"])

_ANY_STAFF = ("tenant_admin", "dpo", "compliance_officer", "platform_admin")


@router.post("/sources", response_model=RegulatoryWatchSourceOut)
def add_source(
    req: RegulatoryWatchSourceIn, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("platform_admin")),
):
    source = RegulatoryWatchSource(
        name=req.name, url=req.url, source_kind=req.source_kind, category=req.category, created_by=req.created_by,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.get("/sources", response_model=list[RegulatoryWatchSourceOut])
def list_sources(
    category: str | None = None,
    db: Session = Depends(get_session), principal: Principal = Depends(require_role(*_ANY_STAFF)),
):
    query = select(RegulatoryWatchSource).order_by(RegulatoryWatchSource.created_at.desc())
    if category is not None:
        query = query.where(RegulatoryWatchSource.category == category)
    return db.execute(query).scalars().all()


@router.patch("/sources/{source_id}", response_model=RegulatoryWatchSourceOut)
def update_source(
    source_id: str, req: RegulatoryWatchSourceUpdateIn, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("platform_admin")),
):
    source = db.get(RegulatoryWatchSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Regulatory watch source not found.")
    if req.name is not None:
        source.name = req.name
    if req.url is not None:
        source.url = req.url
        source.last_content_hash = None  # a new URL has no meaningful baseline to compare against
        source.last_seen_item_ids = None
    if req.source_kind is not None and req.source_kind != source.source_kind:
        source.source_kind = req.source_kind
        source.last_content_hash = None  # switching detector kind invalidates whatever baseline the old kind kept
        source.last_seen_item_ids = None
    if req.category is not None:
        source.category = req.category
    if req.active is not None:
        source.active = req.active
    db.commit()
    db.refresh(source)
    return source


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(
    source_id: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("platform_admin")),
):
    source = db.get(RegulatoryWatchSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Regulatory watch source not found.")
    db.delete(source)
    db.commit()


@router.post("/sources/{source_id}/check-now", response_model=RegulatoryWatchSourceOut)
def check_now(
    source_id: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("platform_admin")),
):
    source = db.get(RegulatoryWatchSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Regulatory watch source not found.")
    check_source(db, source)
    db.commit()
    db.refresh(source)
    return source


@router.post("/check-all")
def check_all(
    db: Session = Depends(get_session), principal: Principal = Depends(require_role("platform_admin")),
) -> dict:
    """Also the cron-callable maintenance endpoint for a deployment with
    no in-process scheduler running, mirroring
    POST /webhooks/deliveries/process-due."""
    return check_all_sources(db)


@router.get("/alerts", response_model=list[RegulatoryWatchAlertOut])
def list_alerts(
    status: str | None = None, limit: int = 100, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role(*_ANY_STAFF)),
):
    query = select(RegulatoryWatchAlert)
    if status is not None:
        try:
            query = query.where(RegulatoryWatchAlert.status == RegulatoryWatchAlertStatus(status))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Unknown status '{status}'.")
    return db.execute(query.order_by(RegulatoryWatchAlert.detected_at.desc()).limit(limit)).scalars().all()


@router.post("/alerts/{alert_id}/acknowledge", response_model=RegulatoryWatchAlertOut)
def acknowledge_alert(
    alert_id: str, req: RegulatoryWatchAcknowledgeIn, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("platform_admin")),
):
    alert = db.get(RegulatoryWatchAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    if alert.status == RegulatoryWatchAlertStatus.ACKNOWLEDGED:
        raise HTTPException(status_code=409, detail="This alert was already acknowledged.")
    alert.status = RegulatoryWatchAlertStatus.ACKNOWLEDGED
    alert.acknowledged_by = req.acknowledged_by
    alert.note = req.note
    alert.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)
    return alert
