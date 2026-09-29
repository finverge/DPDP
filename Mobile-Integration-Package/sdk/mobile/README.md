# ConsentBridge Mobile Wrappers

Thin native wrappers around the same [`dpdp-consent-widget.js`](../dpdp-consent-widget.js) the web
and React integrations use — **not** native re-implementations of the consent-capture UI. Every
purpose toggle, notice fetch, and `/consents/capture` call runs inside a WebView, running the exact
widget code the other two integrations run. That's a deliberate tradeoff: one real, tested,
DPDP-compliant implementation behind three integration surfaces, instead of three separately
maintained ones that could quietly drift apart on compliance behavior. See the top comment of each
platform's source file for the full rationale.

## ⚠️ Honest status

**Neither of these has been compiled or run.** This SDK was built and verified on a Windows machine
with no Xcode/Swift toolchain and no JDK/Android SDK/Gradle toolchain — confirmed by hand (`swiftc`,
`xcodebuild`, `java`, `kotlinc`, `gradle` are all absent here). Both files are written carefully
against real, current, stable platform APIs (`WKWebView` on iOS, `android.webkit.WebView` on
Android — neither is exotic or fast-moving), but **compile and smoke-test both on a real Mac/Xcode and
Android Studio setup before shipping**. This is the same "flagged, not silently passed off as
verified" discipline the rest of ConsentBridge holds itself to — every other piece of this platform
was live-tested in a real running app; these two pieces are the exception, stated plainly rather than
glossed over.

## iOS — `ios/`

Swift Package Manager. `ConsentBridgeWidget.swift` exports `ConsentBridgeWidgetView`, a SwiftUI
`UIViewRepresentable` wrapping `WKWebView`. `dpdp-consent-widget.js` is bundled as a real SPM target
resource (`Package.swift`'s `resources: [.copy(...)]`), loaded via `Bundle.module` — no network fetch
of the widget script itself.

```swift
ConsentBridgeWidgetView(
    config: ConsentBridgeConfig(
        apiBaseUrl: "https://consent.your-domain.example",
        tenantId: "your-tenant-id",
        dataPrincipalId: currentUserId,
        purposes: [
            ConsentPurpose(
                key: "kyc", label: "KYC & loan processing", required: true,
                grants: [ConsentGrant(dataCategory: "PAN & Identity", purpose: "KYC & loan processing")]
            )
        ]
    ),
    onChange: { granted in /* granted: [String] */ }
)
```

Add via Xcode: File → Add Package Dependencies → Add Local... → point at `sdk/mobile/ios`.

## Android — `android/`

Gradle library module (`com.finverge.consentbridge`). `ConsentBridgeWidgetView` extends `FrameLayout`,
wraps a plain `android.webkit.WebView`, and bridges the widget's `onChange` via
`addJavascriptInterface`. `dpdp-consent-widget.js` ships as a module asset
(`src/main/assets/dpdp-consent-widget.js`), loaded from `context.assets` — no network fetch of the
widget script itself.

```kotlin
val widget = ConsentBridgeWidgetView(context)
widget.onChange = { granted -> /* granted: List<String> */ }
widget.load(
    ConsentBridgeConfig(
        apiBaseUrl = "https://consent.your-domain.example",
        tenantId = "your-tenant-id",
        dataPrincipalId = currentUserId,
        purposes = listOf(
            ConsentPurpose(
                key = "kyc", label = "KYC & loan processing", required = true,
                grants = listOf(ConsentGrant(dataCategory = "PAN & Identity", purpose = "KYC & loan processing"))
            )
        )
    )
)
parentLayout.addView(widget)
```

Add to your app's `settings.gradle.kts`:

```kotlin
include(":consentbridge")
project(":consentbridge").projectDir = file("path/to/sdk/mobile/android/consentbridge")
```

Zero external dependencies on either platform — `org.json` and `android.webkit` ship with the
platform, matching the web widget's own zero-dependency design.

## Not built

- Consent-vault / withdrawal UI natively (same gap the web widget has — see the main SDK README).
- Offline/cached notice fallback if the WebView has no connectivity at load time — the widget shows
  its existing "Privacy notice unavailable right now" error state, same as on web.
- CocoaPods / Maven Central publishing — these are source-distributed (SPM local package reference /
  Gradle module include) today, same "not yet published" honesty as the npm packages (see the main SDK
  README's "Not yet built").
