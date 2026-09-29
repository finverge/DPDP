"""Phase 3 AI-native capability layer (BRD Sec. 6, Sec. 12 Phase 3) —
deterministic assembly/detection baseline.

Honest scope statement, not a caveat to skim past: none of the functions
in this file call a generative model. There is no LLM provider credential
configured in this environment, and BRD Sec. 6.9 requires any such
provider to be self-hosted or contractually data-localisation-compliant —
not a decision this file should make unilaterally by silently wiring one
in. Every capability here is real, tested, and useful on its own:
detection (drift, breach-risk) and assembly (notice drafting, DPIA
drafting, grievance triage, cross-sell gating) from data this platform
already has — the same "deterministic layer first, generative layer as an
optional addition on top later" split the DLP LOS BRD's own CAM feature
(Appendix E.3) already established as house practice. The one place this
matters most is the Rights Assistant (6.3): shipped here as a structured
Q&A over a fixed set of question types, not open natural-language chat —
labelled as such everywhere it's referenced, not oversold as "conversational."

The Regulatory-Change Watch Agent (6.6) lives in app/regulatory_watch.py,
not here — it isn't detection over data this platform already has, it's
best-effort page-change hashing over external government sources (no
official machine-readable feed exists, confirmed by hand; see that
module's docstring for the same honest-scope discipline this one keeps).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ConsentRecord, MaskingAuditEvent, MaskingPolicy, DriftFlag, DPOContact,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------- #
# 6.2 Consent-Purpose Drift Detector
# ---------------------------------------------------------------------- #
def check_drift(db: Session, *, tenant_id: str, data_principal_id: str, purpose: str, actor: str) -> DriftFlag | None:
    """Called from POST /masking/apply only when the caller supplied a
    data_principal_id (schemas.MaskingApplyIn) — i.e. only for flows that
    are actually consent-scoped to one principal, not Fraud360-style bulk/
    legitimate-use exports. Flags (does not block) an access for a purpose
    with no active, non-withdrawn consent grant."""
    active = db.execute(
        select(ConsentRecord).where(
            ConsentRecord.tenant_id == tenant_id,
            ConsentRecord.data_principal_id == data_principal_id,
            ConsentRecord.purpose == purpose,
            ConsentRecord.withdrawn_at.is_(None),
        )
    ).scalars().first()
    if active is not None:
        return None
    flag = DriftFlag(
        tenant_id=tenant_id, data_principal_id=data_principal_id, purpose=purpose, actor=actor,
        detail=f"Data shared for purpose '{purpose}' with no active consent grant covering it.",
    )
    db.add(flag)
    return flag


# ---------------------------------------------------------------------- #
# 6.5 Breach-Risk Early-Warning Model
# ---------------------------------------------------------------------- #
def breach_risk_score(db: Session, *, tenant_id: str, window_days: int = 30) -> dict:
    """A weighted score from two real signals this platform already
    tracks: consent-purpose drift (6.2) and masking coverage gaps (every
    /masking/apply call that was blocked for lack of a policy). Weighting
    is a simple, documented, adjustable heuristic — not a trained model —
    consistent with this file's honest-scope statement."""
    since = _utcnow() - timedelta(days=window_days)

    drift_count = len(db.execute(
        select(DriftFlag).where(DriftFlag.tenant_id == tenant_id, DriftFlag.created_at >= since)
    ).scalars().all())
    blocked_count = len(db.execute(
        select(MaskingAuditEvent).where(
            MaskingAuditEvent.tenant_id == tenant_id, MaskingAuditEvent.outcome == "blocked_no_policy",
            MaskingAuditEvent.created_at >= since,
        )
    ).scalars().all())

    # Simple, capped, documented weighting — each drift flag is weighted
    # higher than a coverage gap because it represents data that was
    # actually shared without consent, not merely a share that was
    # correctly refused.
    raw = drift_count * 8 + blocked_count * 3
    score = min(raw, 100)
    return {
        "tenant_id": tenant_id, "window_days": window_days, "score": score,
        "factors": {"drift_flags": drift_count, "masking_blocks": blocked_count},
        "band": "high" if score >= 60 else "medium" if score >= 25 else "low",
    }


# ---------------------------------------------------------------------- #
# 6.1 Plain-Language Notice Generator (structured assembly, not NLP
# simplification of arbitrary legal text — see module docstring)
# ---------------------------------------------------------------------- #
def draft_notice_content(purposes: list[dict], language: str) -> str:
    """purposes: [{"purpose": str, "data_categories": [str, ...]}, ...].
    Assembles clear notice text from structured input using the same
    template shape as the hand-written seed notices (seed_dev_data.py) —
    this is what makes it a genuine drop-in for a DPO drafting a new
    notice, not a toy example."""
    lines = []
    for p in purposes:
        cats = ", ".join(p["data_categories"])
        lines.append(f"We collect and process your {cats} for {p['purpose']}.")
    body = " ".join(lines)
    closing = (
        " You can view, withdraw, or manage any of these permissions at any time from the Privacy Center. "
        "Withdrawing a permission will not affect anything already done on the basis of it. If you have a "
        "concern about how your data is used, you can raise it with our Grievance Officer before approaching "
        "the Data Protection Board of India."
    )
    return body + closing


# ---------------------------------------------------------------------- #
# 6.4 DPIA Co-Pilot — assembly of figures this platform already computes
# ---------------------------------------------------------------------- #
def assemble_dpia_snapshot(db: Session, *, tenant_id: str, window_days: int = 30) -> dict:
    active_consents = db.execute(
        select(ConsentRecord).where(ConsentRecord.tenant_id == tenant_id, ConsentRecord.withdrawn_at.is_(None))
    ).scalars().all()
    data_categories = sorted({c.data_category for c in active_consents})
    purposes = sorted({c.purpose for c in active_consents})

    policies = db.execute(select(MaskingPolicy).where(MaskingPolicy.tenant_id == tenant_id)).scalars().all()
    masking_coverage = {p.purpose: sorted(p.field_rules.keys()) for p in policies}

    risk = breach_risk_score(db, tenant_id=tenant_id, window_days=window_days)
    dpo = db.get(DPOContact, tenant_id)

    return {
        "tenant_id": tenant_id,
        "generated_at": _utcnow().isoformat(),
        "data_categories_processed": data_categories,
        "purposes_in_use": purposes,
        "active_consent_count": len(active_consents),
        "masking_policy_coverage": masking_coverage,
        "breach_risk": risk,
        "dpo_contact_published": dpo is not None,
        "safeguards": [
            "Granular, purpose-scoped consent capture (§6(1))",
            "Default-deny field masking for onward data shares (§8(4)-(5))",
            "Immutable consent + masking audit trail (§6(10), §8(5))",
        ],
    }


# ---------------------------------------------------------------------- #
# 6.8 Grievance Triage & Draft-Response Assistant
# ---------------------------------------------------------------------- #
_HIGH_SEVERITY_CATEGORIES = {"consent / data use", "data sharing"}


def triage_grievance(db, grievance) -> dict:
    """grievance: a Grievance ORM instance already loaded by the caller.
    Returns a suggestion only — the route never applies it; a Compliance
    Officer still calls /grievances/{id}/resolve or /flag-frivolous
    themselves (FSD Sec. 9.8)."""
    from app.models import Grievance  # local import avoids a cycle at module load

    severity = "high" if grievance.category.strip().lower() in _HIGH_SEVERITY_CATEGORIES else "medium"

    prior = db.execute(
        select(Grievance).where(
            Grievance.tenant_id == grievance.tenant_id,
            Grievance.data_principal_id == grievance.data_principal_id,
            Grievance.subject == grievance.subject,
            Grievance.id != grievance.id,
        )
    ).scalars().all()
    frivolous_signal = len(prior) >= 2  # same subject filed 3+ times total

    draft_response = (
        f"Thank you for raising this ({grievance.category}: “{grievance.subject}”). "
        f"We've logged it and will investigate; you'll hear back within our published SLA. "
        f"If this relates to a specific consent or data-sharing event, please share the reference "
        f"ID from your Privacy Center consent history so we can look into it directly."
    )

    return {
        "grievance_id": grievance.id,
        "suggested_severity": severity,
        "frivolous_signal": frivolous_signal,
        "frivolous_signal_reason": f"{len(prior)} prior grievance(s) with the same subject from this Data Principal." if frivolous_signal else None,
        "draft_response": draft_response,
    }


# ---------------------------------------------------------------------- #
# 6.7 Purpose-Gated Recommendation Engine (also completes Module 5 /
# Cross-Selling Enablement, not built in Phase 1)
# ---------------------------------------------------------------------- #
def gate_cross_sell_candidates(db: Session, *, tenant_id: str, data_principal_id: str, catalog: list[dict]) -> list[dict]:
    """catalog: [{"offer_id", "title", "purpose", "required_data_categories": [...]}, ...].
    A candidate is returned only if every required_data_category has an
    active consent grant for exactly that offer's purpose — never
    "shown anyway with a disclosure" (FSD Sec. 7.2). Ranking is a simple,
    documented heuristic (most-covered-categories first), not an ML model."""
    active = db.execute(
        select(ConsentRecord).where(
            ConsentRecord.tenant_id == tenant_id,
            ConsentRecord.data_principal_id == data_principal_id,
            ConsentRecord.withdrawn_at.is_(None),
        )
    ).scalars().all()
    granted_by_purpose: dict[str, set[str]] = {}
    for c in active:
        granted_by_purpose.setdefault(c.purpose, set()).add(c.data_category)

    out = []
    for offer in catalog:
        have = granted_by_purpose.get(offer["purpose"], set())
        need = set(offer["required_data_categories"])
        if not need.issubset(have):
            continue  # discarded, never generated — not shown with a caveat
        out.append({
            **offer,
            "why_you_are_seeing_this": f"Based on your consent for {offer['purpose']} covering: {', '.join(sorted(need))}.",
        })
    out.sort(key=lambda o: len(o["required_data_categories"]), reverse=True)
    return out


# ---------------------------------------------------------------------- #
# 6.3 Rights Assistant — structured Q&A over fixed question types, NOT
# open natural-language chat (see module docstring)
# ---------------------------------------------------------------------- #
RIGHTS_QUESTION_TYPES = ("who_has_my_data", "what_have_i_granted", "how_to_withdraw")


def answer_rights_question(db: Session, *, tenant_id: str, data_principal_id: str, question_type: str) -> str:
    if question_type == "who_has_my_data":
        active = db.execute(
            select(ConsentRecord).where(
                ConsentRecord.tenant_id == tenant_id, ConsentRecord.data_principal_id == data_principal_id,
                ConsentRecord.withdrawn_at.is_(None),
            )
        ).scalars().all()
        if not active:
            return "We don't currently have any active data-sharing permissions on file for you."
        by_purpose: dict[str, list[str]] = {}
        for c in active:
            by_purpose.setdefault(c.purpose, []).append(c.data_category)
        parts = [f"for {purpose}: {', '.join(cats)}" for purpose, cats in by_purpose.items()]
        return "Your data is currently used " + "; ".join(parts) + "."

    if question_type == "what_have_i_granted":
        all_records = db.execute(
            select(ConsentRecord).where(
                ConsentRecord.tenant_id == tenant_id, ConsentRecord.data_principal_id == data_principal_id,
            )
        ).scalars().all()
        active_n = sum(1 for c in all_records if c.withdrawn_at is None)
        withdrawn_n = len(all_records) - active_n
        return f"You have {active_n} active permission(s) and {withdrawn_n} withdrawn permission(s) on record."

    if question_type == "how_to_withdraw":
        return (
            "Open the Privacy Center, look up your record, and select “Withdraw” next to any "
            "permission you'd like to revoke — it takes effect immediately and independently of your "
            "other permissions."
        )

    raise ValueError(f"Unknown question_type '{question_type}' — expected one of {RIGHTS_QUESTION_TYPES}.")
