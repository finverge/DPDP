"""Phase 3 (BRD Sec. 12, Sec. 6) — AI-native capability layer routes.
See app/ai.py's module docstring for the honest scope statement these
routes expose: deterministic detection/assembly, not generative-model
calls. Every route that produces a draft or suggestion is named
accordingly (draft_*, suggested_*) and none of them writes past a
review/approval boundary a human still owns.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai, breach_simulation, consent_analytics, trust_score
from app.auth import Principal, require_role, require_tenant_match
from app.db import get_session
from app.models import DriftFlag, Notice, DPIADraft, Grievance, BreachSimulationRun
from app.schemas import (
    DriftFlagOut, NoticeAIDraftIn, NoticeOut, DPIADraftOut, GrievanceTriageOut,
    CrossSellCandidatesIn, ConsentPatternSummaryOut, TrustScoreOut, BreachSimulationRunOut,
)

router = APIRouter(prefix="/ai", tags=["ai-capabilities"])

_STAFF_ROLES = ("tenant_admin", "dpo", "compliance_officer", "platform_admin")


@router.get("/drift-flags", response_model=list[DriftFlagOut])
def list_drift_flags(
    tenant_id: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role(*_STAFF_ROLES)),
):
    """BRD Sec. 6.2 / P360-18 — surfaced for the compliance dashboard,
    same pattern as any other audit-adjacent listing in this service."""
    require_tenant_match(principal, tenant_id)
    return db.execute(
        select(DriftFlag).where(DriftFlag.tenant_id == tenant_id).order_by(DriftFlag.created_at.desc())
    ).scalars().all()


@router.get("/breach-risk")
def get_breach_risk(
    tenant_id: str, window_days: int = 30, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role(*_STAFF_ROLES)),
):
    """BRD Sec. 6.5 / P360-21."""
    require_tenant_match(principal, tenant_id)
    return ai.breach_risk_score(db, tenant_id=tenant_id, window_days=window_days)


@router.post("/draft-notice", response_model=NoticeOut)
def draft_notice_ai(
    req: NoticeAIDraftIn, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "dpo", "platform_admin")),
):
    """BRD Sec. 6.1 / P360-17. Creates a new draft Notice version exactly
    like POST /notices does — this is a drafting aid on top of that same
    endpoint's storage, not a parallel path. Still needs
    POST /notices/{id}/approve from a DPO before it can back a real
    consent capture (unchanged Phase 1 rule)."""
    require_tenant_match(principal, req.tenant_id)
    content = ai.draft_notice_content([p.model_dump() for p in req.purposes], req.language)
    last = db.execute(
        select(Notice).where(Notice.tenant_id == req.tenant_id, Notice.language == req.language)
        .order_by(Notice.version.desc())
    ).scalars().first()
    notice = Notice(
        tenant_id=req.tenant_id, language=req.language, content=content,
        version=(last.version + 1) if last else 1,
    )
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return notice


@router.post("/draft-dpia/{tenant_id}", response_model=DPIADraftOut)
def draft_dpia(
    tenant_id: str, generated_by: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("dpo", "tenant_admin", "platform_admin")),
):
    """BRD Sec. 6.4 / P360-20. Immutable snapshot — every call creates a
    new row (models.DPIADraft docstring), never overwrites the last one."""
    require_tenant_match(principal, tenant_id)
    snapshot = ai.assemble_dpia_snapshot(db, tenant_id=tenant_id)
    draft = DPIADraft(tenant_id=tenant_id, generated_by=generated_by, snapshot_json=snapshot)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@router.get("/dpia/{tenant_id}", response_model=DPIADraftOut)
def get_latest_dpia(
    tenant_id: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role(*_STAFF_ROLES)),
):
    require_tenant_match(principal, tenant_id)
    draft = db.execute(
        select(DPIADraft).where(DPIADraft.tenant_id == tenant_id).order_by(DPIADraft.created_at.desc())
    ).scalars().first()
    if draft is None:
        raise HTTPException(status_code=404, detail="No DPIA draft generated yet for this tenant.")
    return draft


@router.get("/dpia/{tenant_id}/history", response_model=list[DPIADraftOut])
def get_dpia_history(
    tenant_id: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role(*_STAFF_ROLES)),
):
    require_tenant_match(principal, tenant_id)
    return db.execute(
        select(DPIADraft).where(DPIADraft.tenant_id == tenant_id).order_by(DPIADraft.created_at.desc())
    ).scalars().all()


@router.post("/triage-grievance/{grievance_id}", response_model=GrievanceTriageOut)
def triage_grievance_ai(
    grievance_id: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role("tenant_admin", "compliance_officer", "platform_admin")),
):
    """BRD Sec. 6.8 / P360-24. A suggestion only — see ai.triage_grievance's
    docstring; the route never calls /grievances/{id}/resolve itself."""
    grievance = db.get(Grievance, grievance_id)
    if grievance is None:
        raise HTTPException(status_code=404, detail="Grievance not found.")
    require_tenant_match(principal, grievance.tenant_id)
    return ai.triage_grievance(db, grievance)


@router.post("/cross-sell/candidates")
def cross_sell_candidates(req: CrossSellCandidatesIn, db: Session = Depends(get_session)):
    """BRD Sec. 6.7 / P360-13, P360-23 — completes Module 5 (Cross-Selling
    Enablement), not built in Phase 1. Purpose-gated: see
    ai.gate_cross_sell_candidates's docstring for the hard-gate rule."""
    return ai.gate_cross_sell_candidates(
        db, tenant_id=req.tenant_id, data_principal_id=req.data_principal_id,
        catalog=[c.model_dump() for c in req.catalog],
    )


@router.get("/rights-assistant")
def rights_assistant(tenant_id: str, data_principal_id: str, question_type: str, db: Session = Depends(get_session)):
    """BRD Sec. 6.3 / P360-19. Structured Q&A over a fixed set of
    question_type values — NOT open natural-language chat. See
    ai.RIGHTS_QUESTION_TYPES and this module's docstring."""
    try:
        answer = ai.answer_rights_question(
            db, tenant_id=tenant_id, data_principal_id=data_principal_id, question_type=question_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"question_type": question_type, "answer": answer}


@router.get("/consent-patterns", response_model=ConsentPatternSummaryOut)
def get_consent_patterns(
    tenant_id: str, window_days: int = 90, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role(*_STAFF_ROLES)),
):
    """BRD Sec. 6.10 — deterministic per-purpose grant/withdrawal
    aggregation. See app/consent_analytics.py's module docstring."""
    require_tenant_match(principal, tenant_id)
    return consent_analytics.consent_pattern_summary(db, tenant_id=tenant_id, window_days=window_days)


@router.get("/trust-score", response_model=TrustScoreOut)
def get_trust_score(
    tenant_id: str, window_days: int = 90, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role(*_STAFF_ROLES)),
):
    """BRD Sec. 6.11 — VADER lexicon sentiment over grievance text rolled
    into a documented heuristic score. See app/trust_score.py's module
    docstring for exactly what this is and isn't."""
    require_tenant_match(principal, tenant_id)
    return trust_score.trust_score(db, tenant_id=tenant_id, window_days=window_days)


@router.post("/breach-simulation/{tenant_id}", response_model=BreachSimulationRunOut)
def run_breach_simulation_route(
    tenant_id: str, triggered_by: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role(*_STAFF_ROLES)),
):
    """BRD Sec. 6.12. Read-only scenario battery over real configuration
    state (app/breach_simulation.py) — persisted as an immutable run, same
    pattern as POST /ai/draft-dpia/{tenant_id}, so readiness is trackable
    over time."""
    require_tenant_match(principal, tenant_id)
    result = breach_simulation.run_breach_simulation(db, tenant_id=tenant_id)
    run = BreachSimulationRun(
        tenant_id=tenant_id, triggered_by=triggered_by,
        scenario_results_json=result["scenarios"],
        readiness_score=result["readiness_score"], readiness_band=result["readiness_band"],
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


@router.get("/breach-simulation/{tenant_id}", response_model=BreachSimulationRunOut)
def get_latest_breach_simulation(
    tenant_id: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role(*_STAFF_ROLES)),
):
    require_tenant_match(principal, tenant_id)
    run = db.execute(
        select(BreachSimulationRun).where(BreachSimulationRun.tenant_id == tenant_id)
        .order_by(BreachSimulationRun.created_at.desc())
    ).scalars().first()
    if run is None:
        raise HTTPException(status_code=404, detail="No breach simulation run yet for this tenant.")
    return run


@router.get("/breach-simulation/{tenant_id}/history", response_model=list[BreachSimulationRunOut])
def get_breach_simulation_history(
    tenant_id: str, db: Session = Depends(get_session),
    principal: Principal = Depends(require_role(*_STAFF_ROLES)),
):
    require_tenant_match(principal, tenant_id)
    return db.execute(
        select(BreachSimulationRun).where(BreachSimulationRun.tenant_id == tenant_id)
        .order_by(BreachSimulationRun.created_at.desc())
    ).scalars().all()
