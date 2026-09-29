/**
 * TypeScript definitions for the ConsentBridge consent widget
 * (dpdp-consent-widget.js). Hand-written against the actual runtime
 * source, not auto-generated — kept in sync manually when the widget's
 * config shape changes (see applyTheme()'s `map` and render()'s
 * required-field check in dpdp-consent-widget.js).
 *
 * Runtime shape note: this file is a plain global-attaching script (an
 * IIFE), not an ES module — it has no `export default` and no named
 * runtime exports. Importing "@consentbridge/consent-widget" for its
 * TYPES (`import type { ... }`) is safe and erased at compile time; the
 * *interfaces* below are real `export`s for that purpose. But there is
 * deliberately no runtime `export default DPDPConsentWidget` here,
 * because there is nothing on the JS side for it to correspond to — a
 * plain `import DPDPConsentWidget from "@consentbridge/consent-widget"`
 * would type-check against a lie and get `undefined` at runtime. The
 * one real runtime entry point is the side-effect import documented on
 * `./register` below, after which the widget is only ever reached via
 * the typed `window.DPDPConsentWidget` global this file declares.
 */

export interface DPDPConsentGrant {
  data_category: string;
  purpose: string;
  /** Retention in days. Omit for "until withdrawn". */
  duration_days?: number;
}

export interface DPDPConsentPurpose {
  /** Stable local key — what onChange()/getGrantedPurposes() report, not sent to the API directly. */
  key: string;
  /** Shown as the checkbox label. */
  label: string;
  /** §6(1) — grouping data categories under one purpose is fine; grouping two purposes is not. */
  required: boolean;
  grants: DPDPConsentGrant[];
}

export interface DPDPConsentTheme {
  primaryColor?: string;
  accentColor?: string;
  radius?: string;
  fontFamily?: string;
  fontSize?: string;
  /** Locks out the prefers-color-scheme dark default when set together with textColor — see widget source. */
  background?: string;
  textColor?: string;
  /** Optional — defaults to a guaranteed-contrast-safe value when background/textColor is set without it. */
  mutedBackground?: string;
  mutedTextColor?: string;
  /** Optional fine-tuning; also falls back safely to textColor when background/textColor is locked. */
  mutedForegroundColor?: string;
  accentTextColor?: string;
}

export interface DPDPConsentWidgetConfig {
  /** Base URL of a running dpdp_service instance, e.g. "https://consent.your-domain.example". */
  apiBaseUrl: string;
  /** A Phase 1 loose tenant_id string, or a Phase 2 Tenant registry id — see README "Phase 1 vs Phase 2 tenant identity". */
  tenantId: string;
  /** Your own end-user identifier — the Data Principal this consent is captured for. */
  dataPrincipalId: string;
  /** Must match an approved notice's language (GET /notices/current). Defaults to "English". */
  language?: string;
  purposes: DPDPConsentPurpose[];
  theme?: DPDPConsentTheme;
  /** Fetches the tenant's registered branding (GET /tenants/{id}) and applies it on top of `theme`. Requires a Phase 2 Tenant registry id. */
  autoTheme?: boolean;
  /** Called after every grant/withdraw with the full list of currently granted purpose keys. */
  onChange?: (grantedPurposeKeys: string[]) => void;
}

export interface DPDPConsentWidgetHandle {
  /** Purpose keys currently granted — same list onChange() receives. */
  getGrantedPurposes: () => string[];
  /** Unmounts the widget and clears the container. Call on cleanup (e.g. a React useEffect teardown). */
  destroy: () => void;
}

export interface DPDPConsentWidgetStatic {
  render: (container: HTMLElement, config: DPDPConsentWidgetConfig) => DPDPConsentWidgetHandle;
}

/**
 * Present once dpdp-consent-widget.js has run — via a plain
 * `<script src="...dpdp-consent-widget.js">` tag, or by importing
 * "@consentbridge/consent-widget/register" once for its side effect in
 * a bundler-based app (that subpath IS the same script; importing it
 * purely for the global it attaches, not for any return value).
 */
declare global {
  interface Window {
    DPDPConsentWidget: DPDPConsentWidgetStatic;
  }
}
