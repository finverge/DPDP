# ConsentBridge Widget

Embeddable SDK for [ConsentBridge](../BRD/Finverge_DPDP_BRD_v1.0.docx) — Finverge's DPDP Compliance Platform
(BRD P360-06). One file,
zero dependencies, zero build step — works in a React app, a Vue app, a plain HTML page, or a server-rendered
template. This is the same artifact a third-party fintech integrates and the one Finverge's own DLP LOS
`diy-portal` proves against internally (see `frontend/diy-portal/src/lib/dpdpApi.ts` for the native/typed
integration path — two supported ways to consume the same backend, see "Two ways to integrate" below).

## Quick start

```html
<div id="dpdp-consent"></div>
<script src="https://your-cdn/dpdp-consent-widget.js"></script>
<script>
  DPDPConsentWidget.render(document.getElementById('dpdp-consent'), {
    apiBaseUrl: 'https://consent.finverge.example',   // your DPDP platform instance
    tenantId: 'your-tenant-id',                        // issued when you onboard
    dataPrincipalId: 'user-123',                        // your own user identifier
    language: 'English',
    purposes: [
      {
        key: 'kyc',
        label: 'KYC & loan processing',
        required: true,
        grants: [
          { data_category: 'PAN & Identity', purpose: 'KYC & loan processing' },
          { data_category: 'Address Proof', purpose: 'KYC & loan processing' },
        ],
      },
      {
        key: 'marketing',
        label: 'Marketing communications',
        required: false,
        grants: [{ data_category: 'Contact Details', purpose: 'Marketing / cross-sell communications', duration_days: 365 }],
      },
    ],
    theme: { primaryColor: '#0B5FFF', radius: '10px', fontFamily: 'inherit' },
    // autoTheme: true,  // Phase 2 — fetch tenantId's registered branding
    //                    (POST /tenants, PUT /tenants/{id}/branding) and
    //                    apply it on top of `theme` above. Requires
    //                    tenantId to be a real Tenant registry id, not
    //                    just the loose tenant_id string Phase 1 accepts
    //                    — see "Phase 1 vs Phase 2 tenant identity" below.
    onChange: (grantedPurposeKeys) => {
      // e.g. enable your own "Continue" button once required purposes are granted
    },
  })
</script>
```

**npm-installable, TypeScript-typed, and packable for real publishing** (`npm pack` produces a real
installable tarball — verified by installing it into a fresh app and rendering the widget through it;
not yet run through `npm publish` itself — see "Not yet built" below):

```bash
npm install @consentbridge/consent-widget
```

```ts
import "@consentbridge/consent-widget/register"; // side-effect import: attaches window.DPDPConsentWidget
// then use window.DPDPConsentWidget.render(...) as in the Quick start above — this is a plain
// global-attaching script, not an ES module with a default export (see dpdp-consent-widget.d.ts's
// header comment for why that distinction is stated explicitly, not glossed over)
```

**React?** See [`react/`](react/README.md) — `@consentbridge/react`'s `<ConsentWidget />` component
wraps this same package, nothing reimplemented.

**iOS / Android?** See [`mobile/`](mobile/README.md) — thin native WebView wrappers around this same
widget (⚠️ not compiled/run — no Xcode or Android toolchain in this dev environment, stated plainly
there, not hidden).

Open `demo.html` in this folder (with the DPDP service running on :8110) for a working example — it
deliberately wraps the widget in an unrelated dark-themed, serif-font page to prove the widget only takes on
the four `theme` properties you give it, nothing else from the host page.

## Design principles

- **No framework lock-in.** A `<script>` tag and one function call. No npm install required for a page that
  doesn't already have a build pipeline — `package.json` (Phase 2) makes it installable for teams that do,
  without changing that zero-dependency baseline.
- **Scoped styling.** Every visual choice lives under one CSS class (`.dpdp-consent-widget`) driven entirely
  by `--dpdp-*` custom properties — it cannot leak into, and cannot be silently overridden by, the host page's
  own CSS. `theme` in the config is the *only* supported way to restyle it.
- **Notice-gated by construction.** Every purpose checkbox is disabled until the tenant's approved DPDP §5
  notice has loaded — there is no code path where a grant can be captured without one, matching the platform's
  own server-side rule (`POST /consents/capture` rejects a notice that isn't `approved`).
- **Granular, not bundled.** Each `purposes[]` entry is its own independently toggled, independently
  withdrawable consent purpose (§6(1)) — group data categories under one purpose only when they are genuinely
  necessary for that one purpose (see the KYC example above), never to combine two different purposes under
  one checkbox.

## Two ways to integrate

1. **Drop in the widget** (this file) — fastest path, matching UI across every integrator, you own none of the
   consent-capture UX.
2. **Call the REST API directly** and build your own UI — see `Finverge_DPDP_FSD_v1.0.docx` Sec. 3 for the
   full contract (`GET /notices/current`, `POST /consents/capture`, `POST /consents/{id}/withdraw`,
   `GET /consents`, `GET /consents/{id}/audit`). `frontend/diy-portal/src/lib/dpdpApi.ts` in the DLP LOS
   codebase is a real, typed (TypeScript) example of this path — Finverge's own portal uses its own design
   system rather than this widget, which is exactly the flexibility option 2 is for.

## Backend

Points at any running `dpdp_service` instance (`../dpdp_service/`). For local development:

```bash
cd ../dpdp_service
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8110
```

Then set `apiBaseUrl: 'http://localhost:8110'` and make sure the tenant has an approved notice
(`POST /notices` then `POST /notices/{id}/approve` — see `../dpdp_service/seed_dev_data.py` for a working
example against the `finverge-dlp-los` and `acme-fintech-demo` tenants used by `diy-portal` and `demo.html`
respectively).

## Phase 1 vs Phase 2 tenant identity

Phase 1's notice/consent/masking endpoints accept `tenant_id` as a loose string namespace (e.g.
`"finverge-dlp-los"`, `"acme-fintech-demo"` — never formally registered anywhere). Phase 2 adds a real Tenant
registry (`POST /tenants` → an `id` + API key). The two are **not automatically the same thing** — a tenant
seeded before Phase 2 existed has no corresponding `Tenant` row, so `autoTheme` (which reads
`GET /tenants/{id}`) will silently no-op for it (falls back to your explicit `theme`, never errors). Any
tenant onboarded via `POST /tenants` going forward should use that same `id` as its `tenant_id` everywhere
else (notices, consents, masking policies) to keep the two aligned — this SDK does not enforce that link yet.

## Not yet built (tracked, not silently dropped)

- **Actually running `npm publish`.** The package is publish-ready — TypeScript types, a real `exports` map,
  `publishConfig.access: "public"`, verified via `npm pack` + installing the real tarball into a fresh app and
  rendering the widget through it (React wrapper included) — but publishing to the public npm registry (and
  therefore to jsdelivr/unpkg, which mirror npm automatically — there's no separate manual CDN step) needs
  Finverge's own npm account credentials, which this session doesn't have and shouldn't create unilaterally.
  The command, once ready:
  ```bash
  cd sdk && npm publish        # @consentbridge/consent-widget
  cd sdk/react && npm publish  # @consentbridge/react
  ```
- **CocoaPods / Maven Central for the mobile wrappers.** Source-distributed today (SPM local package
  reference / Gradle module include) — see `mobile/README.md`.
- **The mobile wrappers themselves are unverified** — written, not compiled or run (no Xcode/Android
  toolchain in this environment). See `mobile/README.md`'s "Honest status" before shipping either.
- Consent-vault / withdrawal UI inside the widget itself — today withdrawal is done by re-rendering with the
  purpose unchecked, or via the platform's own `/consents` + `/consents/{id}/withdraw` endpoints directly (see
  `diy-portal`'s `PrivacyCenter.tsx` for a full vault UI built against the same API).
- Enforced Phase-1/Phase-2 tenant-identity linkage (see above) — `autoTheme` degrades gracefully today rather
  than requiring it.
