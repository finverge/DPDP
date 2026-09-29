"""Consent Pattern Analytics (BRD Sec. 6.10) — deterministic aggregation
over consent grants this platform already stores, in the same "detection
over real data, not a trained model" discipline as app/ai.py's module
docstring. Nothing here fits a model or infers from anything ML-shaped:
it is group-by/count/ratio arithmetic over ConsentRecord rows, surfaced so
a tenant can see which purposes users churn out of, the way the BRD add-on
proposal's own example put it — "80% of users revoke consent for
'marketing emails' within 30 days" is exactly a withdrawal-rate query, not
a model prediction.

flagged_purposes below is a simple, documented, adjustable threshold rule
(same shape as app/ai.py's breach_risk_score weighting) — not a
statistically-tuned churn model. A tenant with too few grants for a
purpose to mean anything is excluded via _MIN_SAMPLE rather than flagged
on a misleadingly small sample.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ConsentRecord

_MIN_SAMPLE = 5
_WITHDRAWAL_RATE_FLAG_THRESHOLD = 0.5  # flag a purpose where >=50% of grants are withdrawn


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def consent_pattern_summary(db: Session, *, tenant_id: str, window_days: int = 90) -> dict:
    """Grants created within window_days, grouped by purpose. For each
    purpose: how many were granted, how many have since been withdrawn,
    the withdrawal rate, and — for the withdrawn ones — the median days
    between grant and withdrawal (None when nothing in the purpose has
    been withdrawn yet, not 0, so a UI doesn't misread "no data" as
    "instant withdrawal"). A purpose is flagged when its withdrawal rate
    is at or above _WITHDRAWAL_RATE_FLAG_THRESHOLD and it has at least
    _MIN_SAMPLE grants in the window — the UX/compliance-tuning signal
    the BRD add-on proposal describes."""
    since = _utcnow() - timedelta(days=window_days)
    records = db.execute(
        select(ConsentRecord).where(ConsentRecord.tenant_id == tenant_id, ConsentRecord.granted_at >= since)
    ).scalars().all()

    by_purpose: dict[str, list[ConsentRecord]] = {}
    for r in records:
        by_purpose.setdefault(r.purpose, []).append(r)

    purposes = []
    for purpose, grants in sorted(by_purpose.items()):
        withdrawn = [g for g in grants if g.withdrawn_at is not None]
        granted_count = len(grants)
        withdrawn_count = len(withdrawn)
        withdrawal_rate = withdrawn_count / granted_count if granted_count else 0.0
        days_to_withdrawal = [
            (g.withdrawn_at - g.granted_at).total_seconds() / 86400 for g in withdrawn
        ]
        flagged = granted_count >= _MIN_SAMPLE and withdrawal_rate >= _WITHDRAWAL_RATE_FLAG_THRESHOLD
        purposes.append({
            "purpose": purpose,
            "granted_count": granted_count,
            "withdrawn_count": withdrawn_count,
            "withdrawal_rate": round(withdrawal_rate, 4),
            "median_days_to_withdrawal": round(median(days_to_withdrawal), 1) if days_to_withdrawal else None,
            "flagged": flagged,
            "flag_reason": (
                f"{withdrawn_count}/{granted_count} grants for this purpose were withdrawn within the window "
                f"(>= {int(_WITHDRAWAL_RATE_FLAG_THRESHOLD * 100)}% threshold, sample size >= {_MIN_SAMPLE})."
            ) if flagged else None,
        })

    return {
        "tenant_id": tenant_id,
        "window_days": window_days,
        "total_grants": len(records),
        "purposes": purposes,
        "flagged_purpose_count": sum(1 for p in purposes if p["flagged"]),
    }
