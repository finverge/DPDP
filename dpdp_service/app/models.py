"""SQLAlchemy models — Consent Management Engine (FSD Sec. 3), Grievance +
DPO-contact module (FSD Sec. 8.3 workflow / BRD P360-11).

Tenancy note (HLD Sec. 5): every table carries tenant_id and every query in
routes.py filters on it explicitly — there is no cross-tenant query path.
This is enforced by convention at the route layer here (a single-process
Phase-1 service); HLD Sec. 8's later deployment work is expected to harden
this to a DB-level tenant boundary once this graduates past internal
dogfood (BRD Sec. 12, Phase 2).
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, Boolean, DateTime, Enum, Integer, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NoticeStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    RETIRED = "retired"


class Notice(Base):
    """A tenant's DPDP §5 notice, per language. Versioned, never edited in
    place once approved — approving a new draft retires the previously
    approved one (FSD Sec. 3.1); every consent capture records exactly
    which notice version was shown, so a later notice edit can never
    silently rewrite what a Data Principal actually saw (§6(10) burden of
    proof)."""
    __tablename__ = "notices"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    language: Mapped[str] = mapped_column(String, nullable=False, default="en")
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[NoticeStatus] = mapped_column(
        Enum(NoticeStatus, values_callable=lambda e: [x.value for x in e]),
        default=NoticeStatus.DRAFT, nullable=False,
    )
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "language", "version", name="uq_notice_tenant_lang_version"),)


class ConsentRecord(Base):
    """One row per granted data-category/purpose grant (FSD Sec. 3.2) — a
    capture request with N grants creates N rows, never one bundled row,
    so each purpose can be withdrawn independently (§6(1), §6(4))."""
    __tablename__ = "consent_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    data_principal_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    notice_id: Mapped[str] = mapped_column(String, ForeignKey("notices.id"), nullable=False)
    language: Mapped[str] = mapped_column(String, nullable=False, default="en")
    data_category: Mapped[str] = mapped_column(String, nullable=False)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = until withdrawn; the only field PATCH /consents/{id} may change — see routes.py modify_consent
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    notice: Mapped["Notice"] = relationship()
    audit_events: Mapped[list["ConsentAuditEvent"]] = relationship(
        back_populates="consent_record", order_by="ConsentAuditEvent.created_at",
    )


class ConsentAuditEventType(str, enum.Enum):
    CAPTURED = "captured"
    WITHDRAWN = "withdrawn"
    ACCESSED = "accessed"
    MODIFIED = "modified"  # duration_days changed via PATCH /consents/{id} — see routes.py modify_consent


class ConsentAuditEvent(Base):
    """Immutable audit trail (FSD Sec. 3.4) — the §6(10) burden-of-proof
    evidence. Never updated or deleted; a correction is a new row, not an
    edit to an old one."""
    __tablename__ = "consent_audit_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    consent_record_id: Mapped[str] = mapped_column(String, ForeignKey("consent_records.id"), nullable=False, index=True)
    event_type: Mapped[ConsentAuditEventType] = mapped_column(
        Enum(ConsentAuditEventType, values_callable=lambda e: [x.value for x in e]), nullable=False,
    )
    actor: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    consent_record: Mapped["ConsentRecord"] = relationship(back_populates="audit_events")


class GrievanceStatus(str, enum.Enum):
    OPEN = "Open"
    IN_PROGRESS = "In Progress"
    RESOLVED = "Resolved"
    REJECTED = "Rejected"


class Grievance(Base):
    """Grievance intake (§13, FSD Sec. 8.3) — SLA-tracked via created_at/
    resolved_at at the call site (BRD P360-11); is_frivolous surfaces the
    §15(d)/§28(12) path without deleting the record."""
    __tablename__ = "grievances"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    data_principal_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[GrievanceStatus] = mapped_column(
        Enum(GrievanceStatus, values_callable=lambda e: [x.value for x in e]),
        default=GrievanceStatus.OPEN, nullable=False,
    )
    is_frivolous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)


class MaskingPolicy(Base):
    """Data Minimization Engine — FSD Sec. 4.1. One policy per
    (tenant_id, purpose): field_rules maps a field name to a strategy
    ("allow" | "redact" | "mask_last4" | "omit"). A field not present in
    field_rules is omitted by default when the policy is applied
    (FSD Sec. 4.2's default-deny/fail-closed rule applies per-field, not
    just per-policy-existence) — minimization is the default, not an
    opt-in."""
    __tablename__ = "masking_policies"
    __table_args__ = (UniqueConstraint("tenant_id", "purpose", name="uq_masking_policy_tenant_purpose"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    field_rules: Mapped[dict] = mapped_column(JSON, nullable=False)  # {"field_name": "allow"|"redact"|"mask_last4"|"omit"}
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class MaskingAuditEvent(Base):
    """FSD Sec. 4.3 — every masking application AND every block (no
    matching policy) is logged here, the §8(5) "reasonable security
    safeguards" evidence trail. Never just the successes."""
    __tablename__ = "masking_audit_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)  # "applied" | "blocked_no_policy"
    fields_in: Mapped[int] = mapped_column(Integer, nullable=False)
    fields_out: Mapped[int] = mapped_column(Integer, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DPOContact(Base):
    """Published DPO/grievance-officer contact per tenant (§8(9)-(10)) —
    one row per tenant, upserted, never duplicated."""
    __tablename__ = "dpo_contacts"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# =========================================================================
# Phase 2 (BRD Sec. 12) — External SaaS launch: multi-tenant onboarding,
# white-label branding, usage metering (the data layer billing runs on —
# this service never collects payment; see routes_tenants.py docstring).
# =========================================================================
class Tenant(Base):
    """Self-service tenant record — the thing every other table's
    tenant_id foreign-keys to conceptually (no DB-level FK, per the
    tenant-isolation-by-convention note in this file's header; Phase 2
    adds the record of the tenant itself, Phase 1 only ever assumed one
    existed).

    api_key handling (app/tenant_keys.py): hashed at rest with the same
    bcrypt primitive as user passwords — the plaintext key is returned
    only once, at creation or rotation, never stored or re-shown, same
    discipline as WebhookSubscription.secret. api_key_prefix is a short,
    non-secret slice of the plaintext kept so an admin can recognize
    which key is configured without ever re-revealing the whole thing.
    previous_api_key_hash/previous_api_key_expires_at hold the prior key
    through a grace window after a rotation, so an in-flight integration
    doesn't break the instant a key rotates. api_key_rotate_by drives
    scheduled automatic rotation (app/tenant_keys.py's background loop,
    same shape as the webhook-retry and regulatory-watch loops) on top
    of on-demand manual rotation.

    Honest scope note: no route currently verifies a presented api_key
    against anything (see routes_tenants.py — the key has always been
    generated but never enforced, a pre-existing Phase 1/2 gap this work
    doesn't close). This makes the *lifecycle* real — hashed, rotatable,
    time-bounded — without inventing a new authentication mechanism
    nobody asked for; verify_api_key() exists and is tested, ready for
    whichever future route actually gates on it."""
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String, nullable=False)
    api_key_prefix: Mapped[str] = mapped_column(String, nullable=False, index=True)
    api_key_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    api_key_rotate_by: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    previous_api_key_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    previous_api_key_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan: Mapped[str] = mapped_column(String, nullable=False, default="trial")  # trial | saas | white_label
    brand_primary_color: Mapped[str | None] = mapped_column(String, nullable=True)
    brand_logo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    brand_font_family: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class User(Base):
    """An admin-portal login (FSD Sec. 2 actors: tenant_admin, dpo,
    compliance_officer; platform_admin has tenant_id=None). Copied
    login/password pattern from Fraud360's tenant_service — bcrypt hash,
    a simple failed-attempt lockout, nothing more (no MFA/SSO/sessions
    yet, see security.py docstring)."""
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)  # None only for platform_admin
    email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # platform_admin | tenant_admin | dpo | compliance_officer
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class UsageEvent(Base):
    """One row per billable/meterable action (BRD Sec. 8 "B2B SaaS (API
    usage)" pricing lever) — written alongside, never instead of, each
    action's own domain audit event (ConsentAuditEvent, MaskingAuditEvent,
    etc.). Kept as its own table rather than derived by counting those
    other tables at billing time, so a schema change to any one domain
    table can never silently change historical usage/billing figures."""
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)  # e.g. "consent.capture", "masking.apply"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


# =========================================================================
# Phase 3 (BRD Sec. 12 / Sec. 6) — AI-native capability layer, deterministic
# baseline. Every capability here is assembly/detection logic, not a
# generative-model call (BRD Sec. 6.9's data-residency constraint and the
# "no LLM provider credential available in this environment" limitation
# both point the same direction) — see ai.py's module docstring for the
# honest scope statement this file's models back.
# =========================================================================
class DriftFlag(Base):
    """Consent-Purpose Drift Detector output (BRD Sec. 6.2, P360-18) — a
    masking/apply event for a purpose the actor's data principal has no
    active (non-withdrawn) consent grant covering. Detection only; never
    auto-blocks the access that triggered it (FSD Sec. 9.2)."""
    __tablename__ = "drift_flags"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    data_principal_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


# =========================================================================
# Webhooks (FSD Sec. 5.4) — outbound event delivery to tenant-registered
# Processor endpoints. See app/webhooks.py for the signing/retry engine
# these two tables back.
# =========================================================================
class WebhookSubscription(Base):
    """A tenant-registered subscription to one or more event types (FSD
    Sec. 5.4). `secret` HMAC-signs every delivery (X-ConsentBridge-
    Signature) so a receiver can verify a payload actually came from this
    platform — returned in full only once, on creation; never re-exposed
    by GET (see routes_webhooks.py)."""
    __tablename__ = "webhook_subscriptions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    secret: Mapped[str] = mapped_column(String, nullable=False)
    events: Mapped[list] = mapped_column(JSON, nullable=False)  # subset of app.webhooks.WEBHOOK_EVENT_TYPES
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class WebhookDeliveryStatus(str, enum.Enum):
    PENDING = "pending"    # awaiting first attempt or a scheduled retry
    SUCCESS = "success"
    FAILED = "failed"      # exhausted WEBHOOK_MAX_ATTEMPTS — visible, never silently dropped (FSD Sec. 5.4)


class WebhookDelivery(Base):
    """One row per (subscription, event) delivery, carried through every
    retry attempt rather than one row per attempt — attempt_count/
    last_attempt_at/response_* always reflect the most recent try, and a
    row that never reaches status=success ends at status=failed, still
    queryable on the tenant's compliance dashboard (FSD Sec. 5.4's
    "not silently dropped" requirement) rather than deleted."""
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    subscription_id: Mapped[str] = mapped_column(String, ForeignKey("webhook_subscriptions.id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[WebhookDeliveryStatus] = mapped_column(
        Enum(WebhookDeliveryStatus, values_callable=lambda e: [x.value for x in e]),
        default=WebhookDeliveryStatus.PENDING, nullable=False, index=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    subscription: Mapped["WebhookSubscription"] = relationship()


# =========================================================================
# Regulatory-Change Watch Agent (BRD Sec. 6.6) — platform-level, not
# tenant-scoped (see app/regulatory_watch.py module docstring for why).
# =========================================================================
class RegulatoryWatchSource(Base):
    """A URL a platform_admin has asked the watcher to periodically check
    for changes — e.g. MeitY's DPDP framework page, a PIB release list,
    egazette.gov.in, or RBI's real notifications RSS feed
    (rbi.org.in/notifications_rss.xml — confirmed genuine and current,
    unlike MeitY which 403s automated requests). Curated by hand; nothing
    here is auto-discovered.

    source_kind picks which detector app/regulatory_watch.py runs:
    "page_hash" (default — whole-body hash diff, the only kind that
    existed before RBI's feed was found) or "rss" (per-item diff against
    a real machine-readable feed — a genuine upgrade where one exists,
    since it can name exactly which notification is new rather than just
    "the page changed, go look"). last_seen_item_ids is "rss"-only
    bookkeeping: the most recent items' stable identifiers (their <link>,
    or a hash of title+date if a feed omits one), capped and refreshed
    each check, mirroring last_content_hash's role for "page_hash".

    category is a free-text compliance-domain tag, not a fixed enum —
    "dpdp" (default) for the platform's own DPDP Act sources, "ckycr" for
    CERSAI/CKYCR sources tracked here so TrustGrid (Finverge's CKYC
    Connector product) gets a real compliance-posture view without a
    second watcher being built from scratch; any other tenant/product
    line can reuse the same mechanism the same way."""
    __tablename__ = "regulatory_watch_sources"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    source_kind: Mapped[str] = mapped_column(String, nullable=False, default="page_hash")  # "page_hash" | "rss"
    category: Mapped[str] = mapped_column(String, nullable=False, default="dpdp")  # free text, no fixed enum — e.g. "dpdp" (default) or "ckycr" (CERSAI/CKYCR sources, tracked here for TrustGrid's compliance posture rather than standing up a second watcher)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    last_seen_item_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # "rss" sources only
    last_status: Mapped[str | None] = mapped_column(String, nullable=True)  # "ok" | "error" | None (never checked)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class RegulatoryWatchAlertStatus(str, enum.Enum):
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"


class RegulatoryWatchAlert(Base):
    """A detected content change on a watched source — a change *alarm*,
    not a classification of what changed (app/regulatory_watch.py: no LLM
    reads or interprets the page). source_name/url are snapshotted at
    detection time so an alert stays meaningful even if the source is
    later renamed or deleted. A human closes the loop via /acknowledge,
    recording what actually changed and which tenant config fields it
    affects (BRD Sec. 6.6) — the platform never infers that itself."""
    __tablename__ = "regulatory_watch_alerts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(String, ForeignKey("regulatory_watch_sources.id"), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    previous_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    new_hash: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # "rss" sources: the new item's title (+ pubDate) — real content, not just "hash changed"; None for "page_hash" sources, which have no such content to name
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    status: Mapped[RegulatoryWatchAlertStatus] = mapped_column(
        Enum(RegulatoryWatchAlertStatus, values_callable=lambda e: [x.value for x in e]),
        default=RegulatoryWatchAlertStatus.NEW, nullable=False, index=True,
    )
    acknowledged_by: Mapped[str | None] = mapped_column(String, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class DPIADraft(Base):
    """DPIA Co-Pilot output (BRD Sec. 6.4, P360-20) — same immutable-
    snapshot discipline as DLP LOS's own Credit Appraisal Memo (BRD
    Appendix E.3): a document used to evidence a DPO's risk assessment
    must reflect what was actually known when generated, not drift if the
    underlying figures change later. GET returns the latest; history is
    independently retrievable. Never auto-filed — a DPO reviews, edits
    (outside this system, today) and owns it (FSD Sec. 9.4)."""
    __tablename__ = "dpia_drafts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    generated_by: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class BreachSimulationRun(Base):
    """Automated Breach Simulation & Stress Testing output (BRD Sec. 6.12,
    app/breach_simulation.py) — same immutable-snapshot discipline as
    DPIADraft above: persisted so a tenant's readiness trend is visible
    over time (useful for board/compliance reporting), never overwritten
    by a later run. See app/breach_simulation.py's module docstring for
    the honest scope statement this table backs — a deterministic
    configuration-readiness check, not a live penetration test."""
    __tablename__ = "breach_simulation_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    triggered_by: Mapped[str] = mapped_column(String, nullable=False)
    scenario_results_json: Mapped[list] = mapped_column(JSON, nullable=False)
    readiness_score: Mapped[int] = mapped_column(Integer, nullable=False)
    readiness_band: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
