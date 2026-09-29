"""Automated Breach Simulation & Stress Testing (BRD Sec. 6.12) — a
battery of deterministic readiness scenarios run against a tenant's REAL
configuration state: masking-policy coverage, API-key rotation hygiene,
breach-notification webhook wiring, published DPO contact, and grievance
SLA backlog.

Honest scope statement, same discipline as this file's siblings (app/ai.py,
app/regulatory_watch.py): this is NOT a live penetration test, NOT fault
injection against production traffic, and NOT a fabricated/random
"pretend breach" that writes fake rows into the consent/masking audit
trail — doing that would pollute the very tables §6(10) depends on for
burden-of-proof. Every scenario here is read-only. It evaluates what a
real incident would find TODAY using tables this platform already has —
the same "deterministic assembly over real data" pattern breach_risk_score
and assemble_dpia_snapshot (app/ai.py) already use. "Simulation" is meant
in the fire-drill sense: walking a scripted what-if against real
conditions, not literally starting a fire.

Each scenario returns pass/warning/fail plus a human-readable detail and
remediation step. The overall readiness score is a simple, documented,
adjustable weighting (same style as breach_risk_score) — not a
statistically calibrated risk model, and deliberately NOT called "band:
high/medium/low" the way breach_risk_score is, since there "high" means
high risk and here a higher score means better readiness — using the
same words for opposite meanings across two dashboards on the same page
would be a real usability bug, not just a naming nit.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ConsentRecord, MaskingPolicy, Tenant, WebhookSubscription, DPOContact,
    Grievance, GrievanceStatus,
)

_GRIEVANCE_SLA_DAYS = 30  # matches FSD Sec. 8.3's "SLA-tracked" language; no shorter contractual SLA is configured anywhere else in this service today


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """Same SQLite tz-naive round-trip issue fixed in tenant_keys.py/
    routes_auth.py — normalize before comparing against a tz-aware _utcnow()."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _scenario_masking_coverage_gap(db: Session, tenant_id: str) -> dict:
    """The 'consent-drift event' scenario from the BRD add-on proposal:
    for every purpose with at least one active (non-withdrawn) consent
    grant, is there a masking policy covering it at all? A purpose with
    active consent and zero masking policy would leak every field,
    unmasked, the instant it's accessed — the same signal
    breach_risk_score's drift_flags factor measures reactively, after an
    access has already happened. This scenario asks the question
    pre-emptively, from configuration alone."""
    active_purposes = {
        r.purpose for r in db.execute(
            select(ConsentRecord).where(ConsentRecord.tenant_id == tenant_id, ConsentRecord.withdrawn_at.is_(None))
        ).scalars().all()
    }
    policy_purposes = {
        p.purpose for p in db.execute(
            select(MaskingPolicy).where(MaskingPolicy.tenant_id == tenant_id)
        ).scalars().all()
    }
    gaps = sorted(active_purposes - policy_purposes)
    if not active_purposes:
        return {
            "id": "masking_coverage_gap", "title": "Masking policy coverage for actively-consented purposes",
            "status": "pass", "detail": "No active consent grants yet — nothing to cover.", "remediation": None,
        }
    if gaps:
        return {
            "id": "masking_coverage_gap", "title": "Masking policy coverage for actively-consented purposes",
            "status": "fail",
            "detail": f"{len(gaps)} purpose(s) have active consent grants but no masking policy: {', '.join(gaps)}. "
                      f"An access for these purposes today would return every field unmasked.",
            "remediation": "Add a masking policy for each listed purpose (Masking Policies screen) before it is used in any real export.",
        }
    return {
        "id": "masking_coverage_gap", "title": "Masking policy coverage for actively-consented purposes",
        "status": "pass", "detail": f"All {len(active_purposes)} actively-consented purpose(s) have a masking policy.",
        "remediation": None,
    }


def _scenario_api_key_exposure_window(db: Session, tenant_id: str) -> dict:
    """The 'API key leak' scenario: how large is the window during which
    a leaked key would still work? Flags a key overdue for its scheduled
    rotation (app/tenant_keys.py's 90-day cadence) and a previous key
    still valid noticeably longer than the documented 48h grace period —
    a bug, not a feature, if it ever happens."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return {
            "id": "api_key_exposure_window", "title": "API key rotation hygiene",
            "status": "fail", "detail": "No tenant record found.", "remediation": "Confirm the tenant exists.",
        }
    now = _utcnow()
    overdue_days = (now - _aware(tenant.api_key_rotate_by)).total_seconds() / 86400

    grace_overrun_hours = None
    if tenant.previous_api_key_expires_at is not None:
        grace_hours = (_aware(tenant.previous_api_key_expires_at) - _aware(tenant.api_key_created_at)).total_seconds() / 3600
        if grace_hours > 48 + 1:  # +1h tolerance for scheduler jitter
            grace_overrun_hours = round(grace_hours - 48, 1)

    if overdue_days > 0:
        return {
            "id": "api_key_exposure_window", "title": "API key rotation hygiene",
            "status": "warning" if overdue_days < 7 else "fail",
            "detail": f"Current API key is {round(overdue_days, 1)} day(s) past its scheduled rotation.",
            "remediation": "Trigger POST /tenants/{id}/rotate-api-key, or wait for the hourly automatic-rotation loop to catch it.",
        }
    if grace_overrun_hours is not None:
        return {
            "id": "api_key_exposure_window", "title": "API key rotation hygiene",
            "status": "warning",
            "detail": f"Previous key's grace period is running {grace_overrun_hours}h longer than the documented 48h window.",
            "remediation": "Investigate why the previous key wasn't invalidated on schedule.",
        }
    return {
        "id": "api_key_exposure_window", "title": "API key rotation hygiene",
        "status": "pass", "detail": f"Key rotates on schedule ({round(-overdue_days, 1)} day(s) until next rotation).",
        "remediation": None,
    }


def _scenario_breach_notification_wiring(db: Session, tenant_id: str) -> dict:
    """Would anyone actually be notified if breach.detected fired right now?"""
    subs = db.execute(
        select(WebhookSubscription).where(
            WebhookSubscription.tenant_id == tenant_id, WebhookSubscription.active.is_(True),
        )
    ).scalars().all()
    wired = [s for s in subs if "breach.detected" in s.events]
    if wired:
        return {
            "id": "breach_notification_wiring", "title": "Breach-notification webhook wiring",
            "status": "pass", "detail": f"{len(wired)} active subscription(s) would receive breach.detected.",
            "remediation": None,
        }
    return {
        "id": "breach_notification_wiring", "title": "Breach-notification webhook wiring",
        "status": "fail",
        "detail": "No active webhook subscription is wired to breach.detected — a real breach event would fire and nothing downstream would be notified.",
        "remediation": "Register a webhook subscription (Webhooks screen) including breach.detected in its events.",
    }


def _scenario_dpo_contact_published(db: Session, tenant_id: str) -> dict:
    dpo = db.get(DPOContact, tenant_id)
    if dpo is not None:
        return {
            "id": "dpo_contact_published", "title": "DPO / grievance-officer contact published",
            "status": "pass", "detail": f"Published: {dpo.name} <{dpo.email}>.", "remediation": None,
        }
    return {
        "id": "dpo_contact_published", "title": "DPO / grievance-officer contact published",
        "status": "fail",
        "detail": "No DPO contact on file — §8(9)-(10) requires one to be published, and a breach intimation needs somewhere to point.",
        "remediation": "Set the DPO contact on the Settings screen.",
    }


def _scenario_grievance_sla_backlog(db: Session, tenant_id: str) -> dict:
    cutoff = _utcnow() - timedelta(days=_GRIEVANCE_SLA_DAYS)
    open_grievances = db.execute(
        select(Grievance).where(
            Grievance.tenant_id == tenant_id,
            Grievance.status.in_([GrievanceStatus.OPEN, GrievanceStatus.IN_PROGRESS]),
        )
    ).scalars().all()
    overdue = [g for g in open_grievances if _aware(g.created_at) < cutoff]
    if not overdue:
        return {
            "id": "grievance_sla_backlog", "title": f"Grievance backlog within {_GRIEVANCE_SLA_DAYS}-day SLA",
            "status": "pass", "detail": f"{len(open_grievances)} open grievance(s), none over {_GRIEVANCE_SLA_DAYS} days old.",
            "remediation": None,
        }
    return {
        "id": "grievance_sla_backlog", "title": f"Grievance backlog within {_GRIEVANCE_SLA_DAYS}-day SLA",
        "status": "warning" if len(overdue) < 3 else "fail",
        "detail": f"{len(overdue)} of {len(open_grievances)} open grievance(s) are older than {_GRIEVANCE_SLA_DAYS} days.",
        "remediation": "Triage and resolve the oldest open grievances (Grievances screen, or POST /ai/triage-grievance/{id} for a draft response).",
    }


_SCENARIOS = (
    _scenario_masking_coverage_gap,
    _scenario_api_key_exposure_window,
    _scenario_breach_notification_wiring,
    _scenario_dpo_contact_published,
    _scenario_grievance_sla_backlog,
)

_STATUS_POINTS = {"pass": 20, "warning": 10, "fail": 0}  # 5 scenarios * 20 pts = 100 max


def run_breach_simulation(db: Session, *, tenant_id: str) -> dict:
    results = [scenario(db, tenant_id) for scenario in _SCENARIOS]
    score = sum(_STATUS_POINTS[r["status"]] for r in results)
    band = "strong" if score >= 80 else "needs_attention" if score >= 50 else "weak"
    return {
        "tenant_id": tenant_id,
        "readiness_score": score,
        "readiness_band": band,
        "scenarios": results,
    }
