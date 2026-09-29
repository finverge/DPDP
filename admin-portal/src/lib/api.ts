/**
 * Typed API client for the ConsentBridge admin portal — talks to the same
 * dpdp_service backend the SDK widget and diy-portal integration use
 * (Finverge_DPDP_FSD_v1.2.docx). This is the first real consumer of the
 * admin-facing endpoints (notices draft/approve, masking policies,
 * grievance resolve/triage, DPO/branding settings, AI insights) that were
 * previously API-only — see FSD Sec. 12's "Developer Portal: not built"
 * gap this app closes.
 */
const API_BASE_URL = import.meta.env.VITE_DPDP_API_BASE_URL ?? "http://localhost:8110"
const TOKEN_KEY = "cb_admin_token"
const SESSION_KEY = "cb_admin_session"

export interface Session {
  role: string
  tenantId: string | null
  email: string
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function getSession(): Session | null {
  const raw = localStorage.getItem(SESSION_KEY)
  return raw ? JSON.parse(raw) : null
}
export function setSession(token: string, session: Session) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(SESSION_KEY, JSON.stringify(session))
}
export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(SESSION_KEY)
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

async function request<T>(path: string, options?: RequestInit, auth = true): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(options?.headers as Record<string, string>) }
  if (auth && token) headers["Authorization"] = `Bearer ${token}`

  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers })
  if (res.status === 401) {
    clearSession()
    window.location.assign("/login")
    throw new ApiError("Session expired. Please log in again.", 401)
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    const message = Array.isArray(body.detail) ? body.detail.map((d: { msg: string }) => d.msg).join("; ") : body.detail
    throw new ApiError(message, res.status)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------- //
// Types
// ---------------------------------------------------------------------- //
export interface Tenant {
  id: string; name: string; plan: string
  api_key_prefix: string; api_key_created_at: string; api_key_rotate_by: string
  previous_api_key_expires_at: string | null
  brand_primary_color: string | null; brand_logo_url: string | null; brand_font_family: string | null
  created_at: string
}
export interface TenantCreated extends Tenant { api_key: string }
export interface Notice {
  id: string; tenant_id: string; language: string; version: number; content: string
  status: string; approved_by: string | null; approved_at: string | null; created_at: string
}
export interface MaskingPolicy {
  id: string; tenant_id: string; purpose: string; field_rules: Record<string, string>
  created_by: string; updated_at: string
}
export interface Grievance {
  id: string; tenant_id: string; data_principal_id: string; category: string; subject: string
  description: string; status: string; is_frivolous: boolean; created_at: string
  resolved_at: string | null; resolution_note: string | null; resolved_by: string | null
}
export interface DpoContact { tenant_id: string; name: string; email: string; phone: string | null; updated_at: string }
export interface DriftFlag { id: string; tenant_id: string; data_principal_id: string; purpose: string; actor: string; detail: string; created_at: string }
export interface BreachRisk { tenant_id: string; window_days: number; score: number; band: string; factors: { drift_flags: number; masking_blocks: number } }
export interface DpiaDraft { id: string; tenant_id: string; generated_by: string; snapshot_json: Record<string, unknown>; created_at: string }
export interface GrievanceTriage { grievance_id: string; suggested_severity: string; frivolous_signal: boolean; frivolous_signal_reason: string | null; draft_response: string }
export interface Usage { tenant_id: string; window_days: number; counts: Record<string, number> }
export interface WebhookSubscription {
  id: string; tenant_id: string; url: string; events: string[]; active: boolean
  created_by: string; created_at: string
}
export interface WebhookSubscriptionCreated extends WebhookSubscription { secret: string }
export interface WebhookDelivery {
  id: string; subscription_id: string; tenant_id: string; event_type: string; status: string
  attempt_count: number; next_attempt_at: string; last_attempt_at: string | null
  response_status: number | null; response_snippet: string | null; created_at: string
}
export interface RegulatoryWatchSource {
  id: string; name: string; url: string; source_kind: "page_hash" | "rss"; category: string; active: boolean
  created_by: string; created_at: string
  last_checked_at: string | null; last_status: string | null; last_error: string | null
}
export interface RegulatoryWatchAlert {
  id: string; source_id: string; source_name: string; url: string; detail: string | null; detected_at: string
  status: string; acknowledged_by: string | null; acknowledged_at: string | null; note: string | null
}
export interface ConsentPatternPurpose {
  purpose: string; granted_count: number; withdrawn_count: number; withdrawal_rate: number
  median_days_to_withdrawal: number | null; flagged: boolean; flag_reason: string | null
}
export interface ConsentPatternSummary {
  tenant_id: string; window_days: number; total_grants: number
  purposes: ConsentPatternPurpose[]; flagged_purpose_count: number
}
export interface GrievanceSentiment { grievance_id: string; subject: string; compound: number; band: string }
export interface TrustScore {
  tenant_id: string; window_days: number; grievance_count: number
  score: number | null; band: string | null
  avg_sentiment: number | null; resolution_rate: number | null; frivolous_rate: number | null
  sentiment_by_grievance: GrievanceSentiment[]
}
export interface BreachSimulationScenario {
  id: string; title: string; status: string; detail: string; remediation: string | null
}
export interface BreachSimulationRun {
  id: string; tenant_id: string; triggered_by: string
  scenario_results_json: BreachSimulationScenario[]
  readiness_score: number; readiness_band: string; created_at: string
}

export const api = {
  // Auth
  register: (body: { tenant_id: string | null; email: string; password: string; role: string }) =>
    request("/auth/register", { method: "POST", body: JSON.stringify(body) }, false),
  login: (body: { tenant_id: string | null; email: string; password: string }) =>
    request<{ access_token: string; role: string; tenant_id: string | null }>("/auth/login", { method: "POST", body: JSON.stringify(body) }, false),

  // Tenants
  createTenant: (body: { name: string; plan: string }) => request<TenantCreated>("/tenants", { method: "POST", body: JSON.stringify(body) }, false),
  getTenant: (tenantId: string) => request<Tenant>(`/tenants/${tenantId}`, {}, false),
  updateBranding: (tenantId: string, body: Partial<Pick<Tenant, "brand_primary_color" | "brand_logo_url" | "brand_font_family">>) =>
    request<Tenant>(`/tenants/${tenantId}/branding`, { method: "PUT", body: JSON.stringify(body) }),
  getUsage: (tenantId: string) => request<Usage>(`/tenants/${tenantId}/usage`),
  rotateApiKey: (tenantId: string) => request<TenantCreated>(`/tenants/${tenantId}/rotate-api-key`, { method: "POST" }),

  // Notices
  listNoticesCurrent: (tenantId: string, language: string) =>
    request<Notice>(`/notices/current?tenant_id=${encodeURIComponent(tenantId)}&language=${encodeURIComponent(language)}`, {}, false).catch(() => null),
  draftNotice: (body: { tenant_id: string; language: string; content: string }) => request<Notice>("/notices", { method: "POST", body: JSON.stringify(body) }),
  approveNotice: (noticeId: string, approvedBy: string) =>
    request<Notice>(`/notices/${noticeId}/approve`, { method: "POST", body: JSON.stringify({ approved_by: approvedBy }) }),
  draftNoticeAI: (body: { tenant_id: string; language: string; purposes: { purpose: string; data_categories: string[] }[] }) =>
    request<Notice>("/ai/draft-notice", { method: "POST", body: JSON.stringify(body) }),

  // Masking
  listMaskingPolicies: (tenantId: string) => request<MaskingPolicy[]>(`/masking/policies?tenant_id=${encodeURIComponent(tenantId)}`, {}, false),
  upsertMaskingPolicy: (body: { tenant_id: string; purpose: string; field_rules: Record<string, string>; created_by: string }) =>
    request<MaskingPolicy>("/masking/policies", { method: "PUT", body: JSON.stringify(body) }),

  // Grievances
  listGrievances: (tenantId: string, status?: string) =>
    request<Grievance[]>(`/grievances?tenant_id=${encodeURIComponent(tenantId)}${status ? `&status=${encodeURIComponent(status)}` : ""}`),
  resolveGrievance: (id: string, resolvedBy: string, note: string) =>
    request<Grievance>(`/grievances/${id}/resolve`, { method: "POST", body: JSON.stringify({ resolved_by: resolvedBy, resolution_note: note }) }),
  flagFrivolous: (id: string, flaggedBy: string, note?: string) =>
    request<Grievance>(`/grievances/${id}/flag-frivolous`, { method: "POST", body: JSON.stringify({ flagged_by: flaggedBy, note }) }),
  triageGrievance: (id: string) => request<GrievanceTriage>(`/ai/triage-grievance/${id}`, { method: "POST" }),

  // DPO
  getDpoContact: (tenantId: string) => request<DpoContact>(`/dpo-contact?tenant_id=${encodeURIComponent(tenantId)}`, {}, false).catch(() => null),
  upsertDpoContact: (body: { tenant_id: string; name: string; email: string; phone?: string }) =>
    request<DpoContact>("/dpo-contact", { method: "PUT", body: JSON.stringify(body) }),

  // AI insights
  getDriftFlags: (tenantId: string) => request<DriftFlag[]>(`/ai/drift-flags?tenant_id=${encodeURIComponent(tenantId)}`),
  getBreachRisk: (tenantId: string) => request<BreachRisk>(`/ai/breach-risk?tenant_id=${encodeURIComponent(tenantId)}`),
  generateDpia: (tenantId: string, generatedBy: string) =>
    request<DpiaDraft>(`/ai/draft-dpia/${tenantId}?generated_by=${encodeURIComponent(generatedBy)}`, { method: "POST" }),
  getLatestDpia: (tenantId: string) => request<DpiaDraft>(`/ai/dpia/${tenantId}`).catch(() => null),
  getDpiaHistory: (tenantId: string) => request<DpiaDraft[]>(`/ai/dpia/${tenantId}/history`),

  // Webhooks (FSD Sec. 5.4)
  listWebhookEventTypes: () => request<string[]>("/webhooks/event-types", {}, false),
  listWebhookSubscriptions: (tenantId: string) =>
    request<WebhookSubscription[]>(`/webhooks/subscriptions?tenant_id=${encodeURIComponent(tenantId)}`),
  createWebhookSubscription: (body: { tenant_id: string; url: string; events: string[]; created_by: string }) =>
    request<WebhookSubscriptionCreated>("/webhooks/subscriptions", { method: "POST", body: JSON.stringify(body) }),
  updateWebhookSubscription: (id: string, body: { url?: string; events?: string[]; active?: boolean }) =>
    request<WebhookSubscription>(`/webhooks/subscriptions/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  rotateWebhookSecret: (id: string) =>
    request<WebhookSubscriptionCreated>(`/webhooks/subscriptions/${id}/rotate-secret`, { method: "POST" }),
  deleteWebhookSubscription: (id: string) => request<void>(`/webhooks/subscriptions/${id}`, { method: "DELETE" }),
  listWebhookDeliveries: (tenantId: string, status?: string) =>
    request<WebhookDelivery[]>(`/webhooks/deliveries?tenant_id=${encodeURIComponent(tenantId)}${status ? `&status=${encodeURIComponent(status)}` : ""}`),
  retryWebhookDelivery: (id: string) => request<WebhookDelivery>(`/webhooks/deliveries/${id}/retry`, { method: "POST" }),

  // Regulatory-Change Watch Agent (BRD Sec. 6.6) — platform-level, not tenant-scoped
  listRegWatchSources: (category?: string) =>
    request<RegulatoryWatchSource[]>(`/regulatory-watch/sources${category ? `?category=${encodeURIComponent(category)}` : ""}`),
  addRegWatchSource: (body: { name: string; url: string; created_by: string; source_kind?: "page_hash" | "rss"; category?: string }) =>
    request<RegulatoryWatchSource>("/regulatory-watch/sources", { method: "POST", body: JSON.stringify(body) }),
  updateRegWatchSource: (id: string, body: { name?: string; url?: string; active?: boolean; source_kind?: "page_hash" | "rss"; category?: string }) =>
    request<RegulatoryWatchSource>(`/regulatory-watch/sources/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteRegWatchSource: (id: string) => request<void>(`/regulatory-watch/sources/${id}`, { method: "DELETE" }),
  checkRegWatchSourceNow: (id: string) =>
    request<RegulatoryWatchSource>(`/regulatory-watch/sources/${id}/check-now`, { method: "POST" }),
  checkAllRegWatchSources: () =>
    request<{ checked: number; errors: number; new_alerts: number }>("/regulatory-watch/check-all", { method: "POST" }),
  listRegWatchAlerts: (status?: string) =>
    request<RegulatoryWatchAlert[]>(`/regulatory-watch/alerts${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  acknowledgeRegWatchAlert: (id: string, body: { acknowledged_by: string; note: string }) =>
    request<RegulatoryWatchAlert>(`/regulatory-watch/alerts/${id}/acknowledge`, { method: "POST", body: JSON.stringify(body) }),

  // Consent Pattern Analytics (BRD Sec. 6.10)
  getConsentPatterns: (tenantId: string, windowDays = 90) =>
    request<ConsentPatternSummary>(`/ai/consent-patterns?tenant_id=${encodeURIComponent(tenantId)}&window_days=${windowDays}`),

  // User Sentiment & Trust Scoring (BRD Sec. 6.11)
  getTrustScore: (tenantId: string, windowDays = 90) =>
    request<TrustScore>(`/ai/trust-score?tenant_id=${encodeURIComponent(tenantId)}&window_days=${windowDays}`),

  // Automated Breach Simulation & Stress Testing (BRD Sec. 6.12)
  runBreachSimulation: (tenantId: string, triggeredBy: string) =>
    request<BreachSimulationRun>(`/ai/breach-simulation/${tenantId}?triggered_by=${encodeURIComponent(triggeredBy)}`, { method: "POST" }),
  getLatestBreachSimulation: (tenantId: string) =>
    request<BreachSimulationRun>(`/ai/breach-simulation/${tenantId}`).catch(() => null),
  getBreachSimulationHistory: (tenantId: string) =>
    request<BreachSimulationRun[]>(`/ai/breach-simulation/${tenantId}/history`),
}
