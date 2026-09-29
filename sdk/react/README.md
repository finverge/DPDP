# @consentbridge/react

React wrapper around [`@consentbridge/consent-widget`](../README.md) — the ConsentBridge consent
widget. Mounts and tears down the same vanilla-JS widget every other integration uses; does not
reimplement any consent-capture logic.

## Install

```bash
npm install @consentbridge/consent-widget @consentbridge/react
```

## Usage

```tsx
import "@consentbridge/consent-widget/register"; // once, at your app's entry point
import { ConsentWidget } from "@consentbridge/react";

function ConsentStep() {
  return (
    <ConsentWidget
      apiBaseUrl="https://consent.your-domain.example"
      tenantId="your-tenant-id"
      dataPrincipalId={currentUserId}
      purposes={[
        {
          key: "kyc",
          label: "KYC & loan processing",
          required: true,
          grants: [{ data_category: "PAN & Identity", purpose: "KYC & loan processing" }],
        },
      ]}
      onChange={(grantedPurposeKeys) => {
        // enable your own "Continue" button once required purposes are granted
      }}
    />
  );
}
```

`ConsentWidget` accepts every field `DPDPConsentWidgetConfig` does (see
`@consentbridge/consent-widget`'s types), plus `className`/`style` for the mount `<div>`.

## Behavior notes

- **Remounts, doesn't diff.** The underlying widget has no partial-update API, so a changed
  `apiBaseUrl`/`tenantId`/`dataPrincipalId`/`language`/`autoTheme`/`purposes`/`theme` triggers a fresh
  widget render rather than an attempted in-place update. Correct given how rarely those actually
  change after mount.
- **`onChange` never goes stale, never forces a remount.** Pass a fresh inline arrow function every
  render if you want — it's tracked in a ref and called through a stable wrapper, so it can change
  freely without either dropping in-progress widget state or missing an update.

## Build

```bash
npm run build   # tsc -p tsconfig.json → dist/
```

`@consentbridge/consent-widget` is a `devDependency` pinned to `file:..` for local development against
the sibling package in this repo — real consumers install both from npm and this package's
`peerDependencies` range (`^1.1.0`) applies instead.
