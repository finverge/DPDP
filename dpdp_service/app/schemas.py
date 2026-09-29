"""Pydantic request/response schemas — FSD Sec. 3 (Consent Management
Engine) and Sec. 8.3 (Grievance workflow)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------- #
# Notices
# ---------------------------------------------------------------------- #
class NoticeDraftIn(BaseModel):
    tenant_id: str
    language: str = "en"
    content: str = Field(..., min_length=1)


class NoticeOut(BaseModel):
    id: str
    tenant_id: str
    language: str
    version: int
    content: str
    status: str
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NoticeApproveIn(BaseModel):
    approved_by: str = Field(..., min_length=1, description="DPO/Compliance Officer approving this notice version")


# ---------------------------------------------------------------------- #
# Consent
# ---------------------------------------------------------------------- #
class ConsentGrantIn(BaseModel):
    data_category: str = Field(..., min_length=1)
    purpose: str = Field(..., min_length=1)
    duration_days: int | None = None


class ConsentCaptureIn(BaseModel):
    tenant_id: str
    data_principal_id: str
    notice_id: str
    language: str = "en"
    grants: list[ConsentGrantIn]

    @field_validator("grants")
    @classmethod
    def _non_empty(cls, v: list[ConsentGrantIn]) -> list[ConsentGrantIn]:
        if not v:
            raise ValueError("At least one granular grant is required — bundled/empty consent is rejected (§6(1)).")
        return v


class ConsentRecordOut(BaseModel):
    id: str
    tenant_id: str
    data_principal_id: str
    notice_id: str
    language: str
    data_category: str
    purpose: str
    duration_days: int | None
    granted_at: datetime
    withdrawn_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ConsentWithdrawIn(BaseModel):
    actor: str = "data_principal"
    reason: str | None = None


class ConsentModifyIn(BaseModel):
    """The only editable field on a grant is its retention duration — the
    purpose/data_category that define the grant are never editable
    (models.py's "one row per grant" discipline: changing either is
    actually a different grant, i.e. withdraw + a fresh capture, not a
    modification of this one). Required, not optional-with-default, so a
    caller must state the new duration explicitly (including null, for
    "no longer time-limited") rather than a partial-update field that
    could be silently omitted."""
    duration_days: int | None = Field(..., description="New retention duration in days, or null for until-withdrawn.")
    actor: str = "data_principal"
    reason: str | None = None


class ConsentAuditEventOut(BaseModel):
    id: str
    event_type: str
    actor: str
    detail: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------- #
# Data Minimization & Masking (FSD Sec. 4)
# ---------------------------------------------------------------------- #
_VALID_STRATEGIES = {"allow", "redact", "mask_last4", "mask_account", "mask_device", "mask_ip", "omit"}


class MaskingPolicyIn(BaseModel):
    tenant_id: str
    purpose: str = Field(..., min_length=1)
    field_rules: dict[str, str]
    created_by: str = Field(..., min_length=1)

    @field_validator("field_rules")
    @classmethod
    def _valid_strategies(cls, v: dict[str, str]) -> dict[str, str]:
        bad = {k: s for k, s in v.items() if s not in _VALID_STRATEGIES}
        if bad:
            raise ValueError(f"Unknown masking strategy for field(s) {list(bad.keys())} — expected one of {sorted(_VALID_STRATEGIES)}.")
        return v


class MaskingPolicyOut(BaseModel):
    id: str
    tenant_id: str
    purpose: str
    field_rules: dict[str, str]
    created_by: str
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MaskingApplyIn(BaseModel):
    tenant_id: str
    purpose: str
    actor: str = Field(..., min_length=1)
    records: list[dict] = Field(..., min_length=1, description="One or more flat field->value records to mask.")
    data_principal_id: str | None = Field(
        None, description="Optional. When set, the call is checked against this Data Principal's active "
                           "consent grants for `purpose` (BRD Sec. 6.2 Consent-Purpose Drift Detector). Omit "
                           "for bulk/legitimate-use flows (e.g. Fraud360's exports) that aren't scoped to one "
                           "principal's consent in the first place — omission is correct there, not a gap.",
    )


class MaskingApplyOut(BaseModel):
    outcome: str
    records: list[dict]
    fields_in: int
    fields_out: int


# ---------------------------------------------------------------------- #
# Grievance
# ---------------------------------------------------------------------- #
class GrievanceCreateIn(BaseModel):
    tenant_id: str
    data_principal_id: str
    category: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)


class GrievanceOut(BaseModel):
    id: str
    tenant_id: str
    data_principal_id: str
    category: str
    subject: str
    description: str
    status: str
    is_frivolous: bool
    created_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None
    resolved_by: str | None

    model_config = ConfigDict(from_attributes=True)


class GrievanceResolveIn(BaseModel):
    resolved_by: str = Field(..., min_length=1)
    resolution_note: str = Field(..., min_length=1)


class GrievanceFlagFrivolousIn(BaseModel):
    flagged_by: str = Field(..., min_length=1)
    note: str | None = None


# ---------------------------------------------------------------------- #
# DPO contact
# ---------------------------------------------------------------------- #
class DPOContactIn(BaseModel):
    tenant_id: str
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=3)
    phone: str | None = None


class DPOContactOut(BaseModel):
    tenant_id: str
    name: str
    email: str
    phone: str | None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------- #
# Phase 2 — Tenants (self-service onboarding, white-label, metering)
# ---------------------------------------------------------------------- #
class TenantCreateIn(BaseModel):
    name: str = Field(..., min_length=1)
    plan: str = Field("trial", description="trial | saas | white_label")


class TenantOut(BaseModel):
    """Never carries the plaintext api_key — see TenantCreatedOut. The
    prefix and rotation dates are enough for an admin to recognize which
    key is configured and when it last/next rotates, without re-exposing it."""
    id: str
    name: str
    api_key_prefix: str
    api_key_created_at: datetime
    api_key_rotate_by: datetime
    previous_api_key_expires_at: datetime | None
    plan: str
    brand_primary_color: str | None
    brand_logo_url: str | None
    brand_font_family: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TenantCreatedOut(TenantOut):
    """Returned only once — on POST /tenants and POST /tenants/{id}/
    rotate-api-key — carries the plaintext key the caller must save now.
    Same one-time-reveal discipline as WebhookSubscriptionCreatedOut."""
    api_key: str

    model_config = ConfigDict(from_attributes=True)


class TenantBrandingIn(BaseModel):
    brand_primary_color: str | None = None
    brand_logo_url: str | None = None
    brand_font_family: str | None = None


class TenantUsageOut(BaseModel):
    tenant_id: str
    window_days: int
    counts: dict[str, int]


# ---------------------------------------------------------------------- #
# Phase 3 — AI-native capability layer (app/ai.py)
# ---------------------------------------------------------------------- #
class DriftFlagOut(BaseModel):
    id: str
    tenant_id: str
    data_principal_id: str
    purpose: str
    actor: str
    detail: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NoticeDraftPurposeIn(BaseModel):
    purpose: str
    data_categories: list[str] = Field(..., min_length=1)


class NoticeAIDraftIn(BaseModel):
    tenant_id: str
    language: str = "English"
    purposes: list[NoticeDraftPurposeIn] = Field(..., min_length=1)


class DPIADraftOut(BaseModel):
    id: str
    tenant_id: str
    generated_by: str
    snapshot_json: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GrievanceTriageOut(BaseModel):
    grievance_id: str
    suggested_severity: str
    frivolous_signal: bool
    frivolous_signal_reason: str | None
    draft_response: str


class CrossSellOfferIn(BaseModel):
    offer_id: str
    title: str
    purpose: str
    required_data_categories: list[str] = Field(..., min_length=1)


class CrossSellCandidatesIn(BaseModel):
    tenant_id: str
    data_principal_id: str
    catalog: list[CrossSellOfferIn] = Field(..., min_length=1)


# ---------------------------------------------------------------------- #
# Consent Pattern Analytics (BRD Sec. 6.10, app/consent_analytics.py)
# ---------------------------------------------------------------------- #
class ConsentPatternPurposeOut(BaseModel):
    purpose: str
    granted_count: int
    withdrawn_count: int
    withdrawal_rate: float
    median_days_to_withdrawal: float | None
    flagged: bool
    flag_reason: str | None


class ConsentPatternSummaryOut(BaseModel):
    tenant_id: str
    window_days: int
    total_grants: int
    purposes: list[ConsentPatternPurposeOut]
    flagged_purpose_count: int


# ---------------------------------------------------------------------- #
# User Sentiment & Trust Scoring (BRD Sec. 6.11, app/trust_score.py)
# ---------------------------------------------------------------------- #
class GrievanceSentimentOut(BaseModel):
    grievance_id: str
    subject: str
    compound: float
    band: str


class TrustScoreOut(BaseModel):
    tenant_id: str
    window_days: int
    grievance_count: int
    score: int | None
    band: str | None
    avg_sentiment: float | None
    resolution_rate: float | None
    frivolous_rate: float | None
    sentiment_by_grievance: list[GrievanceSentimentOut]


# ---------------------------------------------------------------------- #
# Automated Breach Simulation & Stress Testing (BRD Sec. 6.12,
# app/breach_simulation.py)
# ---------------------------------------------------------------------- #
class BreachSimulationScenarioOut(BaseModel):
    id: str
    title: str
    status: str
    detail: str
    remediation: str | None


class BreachSimulationRunOut(BaseModel):
    id: str
    tenant_id: str
    triggered_by: str
    scenario_results_json: list[BreachSimulationScenarioOut]
    readiness_score: int
    readiness_band: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------- #
# Webhooks (FSD Sec. 5.4, app/webhooks.py)
# ---------------------------------------------------------------------- #
class WebhookSubscriptionIn(BaseModel):
    tenant_id: str
    url: str = Field(..., min_length=8)
    events: list[str] = Field(..., min_length=1)
    created_by: str = Field(..., min_length=1)

    @field_validator("url")
    @classmethod
    def _https_or_http(cls, v: str) -> str:
        if not (v.startswith("https://") or v.startswith("http://")):
            raise ValueError("url must start with http:// or https://")
        return v

    @field_validator("events")
    @classmethod
    def _known_events(cls, v: list[str]) -> list[str]:
        from app.webhooks import WEBHOOK_EVENT_TYPES
        bad = [e for e in v if e not in WEBHOOK_EVENT_TYPES]
        if bad:
            raise ValueError(f"Unknown event type(s) {bad} — expected a subset of {list(WEBHOOK_EVENT_TYPES)}.")
        return v


class WebhookSubscriptionUpdateIn(BaseModel):
    url: str | None = None
    events: list[str] | None = None
    active: bool | None = None


class WebhookSubscriptionOut(BaseModel):
    id: str
    tenant_id: str
    url: str
    events: list[str]
    active: bool
    created_by: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WebhookSubscriptionCreatedOut(WebhookSubscriptionOut):
    """Returned only once, from POST — carries the plaintext secret the
    receiver needs to verify X-ConsentBridge-Signature. Never re-sent."""
    secret: str


class WebhookDeliveryOut(BaseModel):
    id: str
    subscription_id: str
    tenant_id: str
    event_type: str
    status: str
    attempt_count: int
    next_attempt_at: datetime
    last_attempt_at: datetime | None
    response_status: int | None
    response_snippet: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------- #
# Regulatory-Change Watch Agent (BRD Sec. 6.6, app/regulatory_watch.py)
# ---------------------------------------------------------------------- #
_VALID_SOURCE_KINDS = {"page_hash", "rss"}


class RegulatoryWatchSourceIn(BaseModel):
    name: str = Field(..., min_length=1)
    url: str = Field(..., min_length=8)
    created_by: str = Field(..., min_length=1)
    source_kind: str = Field(
        "page_hash", description="'page_hash' (whole-page hash diff, default) or 'rss' (per-item "
                                  "diff against a real machine-readable feed, e.g. RBI's notifications RSS)."
    )
    category: str = Field(
        "dpdp", min_length=1, description="Compliance domain this source is tracked for — free text, "
                                           "no fixed enum. 'dpdp' (default) for the platform's own DPDP Act "
                                           "sources, 'ckycr' for CERSAI/CKYCR sources tracked for TrustGrid's "
                                           "compliance posture."
    )

    @field_validator("url")
    @classmethod
    def _https_or_http(cls, v: str) -> str:
        if not (v.startswith("https://") or v.startswith("http://")):
            raise ValueError("url must start with http:// or https://")
        return v

    @field_validator("source_kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in _VALID_SOURCE_KINDS:
            raise ValueError(f"Unknown source_kind '{v}' — expected one of {sorted(_VALID_SOURCE_KINDS)}.")
        return v


class RegulatoryWatchSourceUpdateIn(BaseModel):
    name: str | None = None
    url: str | None = None
    active: bool | None = None
    source_kind: str | None = None
    category: str | None = None

    @field_validator("source_kind")
    @classmethod
    def _known_kind(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_SOURCE_KINDS:
            raise ValueError(f"Unknown source_kind '{v}' — expected one of {sorted(_VALID_SOURCE_KINDS)}.")
        return v


class RegulatoryWatchSourceOut(BaseModel):
    id: str
    name: str
    url: str
    source_kind: str
    category: str
    active: bool
    created_by: str
    created_at: datetime
    last_checked_at: datetime | None
    last_status: str | None
    last_error: str | None

    model_config = ConfigDict(from_attributes=True)


class RegulatoryWatchAlertOut(BaseModel):
    id: str
    source_id: str
    source_name: str
    url: str
    detail: str | None
    detected_at: datetime
    status: str
    acknowledged_by: str | None
    acknowledged_at: datetime | None
    note: str | None

    model_config = ConfigDict(from_attributes=True)


class RegulatoryWatchAcknowledgeIn(BaseModel):
    acknowledged_by: str = Field(..., min_length=1)
    note: str = Field(..., min_length=1, description="What actually changed, and which tenant config fields it affects (BRD Sec. 6.6) — or that this was a false positive.")


# ---------------------------------------------------------------------- #
# Admin auth (app/auth.py, app/security.py)
# ---------------------------------------------------------------------- #
class UserRegisterIn(BaseModel):
    tenant_id: str | None = None  # None only for platform_admin
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=8)
    role: str  # platform_admin | tenant_admin | dpo | compliance_officer


class UserOut(BaseModel):
    id: str
    tenant_id: str | None
    email: str
    role: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LoginIn(BaseModel):
    email: str
    password: str
    tenant_id: str | None = None  # disambiguates if the same email exists under multiple tenants


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    tenant_id: str | None
