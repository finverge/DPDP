// ConsentBridgeWidget.swift
//
// A thin SwiftUI/WKWebView wrapper around the SAME dpdp-consent-widget.js
// this SDK ships for web — deliberately NOT a native re-implementation of
// the consent-capture UI. Every purpose toggle, notice fetch, and
// /consents/capture call happens inside the WebView, running the exact
// widget code the web and React integrations run, so there is one real
// compliance implementation behind all three, not three to keep in sync.
//
// HONEST STATUS: written against the current, stable WKWebView / Swift
// APIs, but this Windows dev environment has no Xcode/Swift toolchain —
// it could not be compiled or run here (confirmed: no `swiftc`,
// `xcodebuild` available). Treat this as a careful first draft to
// compile and smoke-test on a real Mac/Xcode setup before shipping, the
// same "flagged, not silently passed off as verified" discipline this
// whole SDK follows for anything not actually run.
//
// Requires: iOS 14+, WebKit. Distributed via Swift Package Manager
// (Package.swift declares dpdp-consent-widget.js as a target resource,
// bundled at build time) — loaded from Bundle.module, not fetched over
// the network. If you're copying this file manually instead of via SPM,
// add dpdp-consent-widget.js to your app target's own Copy Bundle
// Resources build phase and change `Bundle.module` below to `Bundle.main`.

import SwiftUI
import WebKit

// MARK: - Config (mirrors dpdp-consent-widget.d.ts's DPDPConsentWidgetConfig)

public struct ConsentGrant: Codable {
    public var dataCategory: String
    public var purpose: String
    public var durationDays: Int?

    enum CodingKeys: String, CodingKey {
        case dataCategory = "data_category"
        case purpose
        case durationDays = "duration_days"
    }

    public init(dataCategory: String, purpose: String, durationDays: Int? = nil) {
        self.dataCategory = dataCategory
        self.purpose = purpose
        self.durationDays = durationDays
    }
}

public struct ConsentPurpose: Codable {
    public var key: String
    public var label: String
    public var required: Bool
    public var grants: [ConsentGrant]

    public init(key: String, label: String, required: Bool, grants: [ConsentGrant]) {
        self.key = key
        self.label = label
        self.required = required
        self.grants = grants
    }
}

public struct ConsentTheme: Codable {
    public var primaryColor: String?
    public var accentColor: String?
    public var radius: String?
    public var fontFamily: String?
    public var fontSize: String?
    public var background: String?
    public var textColor: String?
    public var mutedBackground: String?
    public var mutedTextColor: String?
    public var mutedForegroundColor: String?
    public var accentTextColor: String?

    public init(
        primaryColor: String? = nil, accentColor: String? = nil, radius: String? = nil,
        fontFamily: String? = nil, fontSize: String? = nil, background: String? = nil,
        textColor: String? = nil, mutedBackground: String? = nil, mutedTextColor: String? = nil,
        mutedForegroundColor: String? = nil, accentTextColor: String? = nil
    ) {
        self.primaryColor = primaryColor
        self.accentColor = accentColor
        self.radius = radius
        self.fontFamily = fontFamily
        self.fontSize = fontSize
        self.background = background
        self.textColor = textColor
        self.mutedBackground = mutedBackground
        self.mutedTextColor = mutedTextColor
        self.mutedForegroundColor = mutedForegroundColor
        self.accentTextColor = accentTextColor
    }
}

public struct ConsentBridgeConfig: Codable {
    public var apiBaseUrl: String
    public var tenantId: String
    public var dataPrincipalId: String
    public var language: String
    public var purposes: [ConsentPurpose]
    public var theme: ConsentTheme?
    public var autoTheme: Bool?

    public init(
        apiBaseUrl: String, tenantId: String, dataPrincipalId: String,
        language: String = "English", purposes: [ConsentPurpose],
        theme: ConsentTheme? = nil, autoTheme: Bool? = nil
    ) {
        self.apiBaseUrl = apiBaseUrl
        self.tenantId = tenantId
        self.dataPrincipalId = dataPrincipalId
        self.language = language
        self.purposes = purposes
        self.theme = theme
        self.autoTheme = autoTheme
    }
}

// MARK: - SwiftUI wrapper

/// Drop-in SwiftUI view: `ConsentBridgeWidgetView(config: ..., onChange: { granted in ... })`
public struct ConsentBridgeWidgetView: UIViewRepresentable {
    private let config: ConsentBridgeConfig
    private let onChange: ([String]) -> Void

    public init(config: ConsentBridgeConfig, onChange: @escaping ([String]) -> Void) {
        self.config = config
        self.onChange = onChange
    }

    public func makeCoordinator() -> Coordinator {
        Coordinator(onChange: onChange)
    }

    public func makeUIView(context: Context) -> WKWebView {
        let contentController = WKUserContentController()
        // JS side does: window.webkit.messageHandlers.consentBridge.postMessage(grantedKeys)
        contentController.add(context.coordinator, name: "consentBridge")

        let webConfiguration = WKWebViewConfiguration()
        webConfiguration.userContentController = contentController

        let webView = WKWebView(frame: .zero, configuration: webConfiguration)
        webView.navigationDelegate = context.coordinator
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.backgroundColor = .clear

        context.coordinator.load(into: webView, config: config)
        return webView
    }

    public func updateUIView(_ webView: WKWebView, context: Context) {
        // The underlying widget has no partial-update API (see the React
        // wrapper's same design note) — a changed config reloads the
        // whole page rather than attempting an in-place JS update.
        if context.coordinator.lastLoadedConfig != config {
            context.coordinator.load(into: webView, config: config)
        }
    }

    public static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "consentBridge")
    }

    public class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        private let onChange: ([String]) -> Void
        fileprivate var lastLoadedConfig: ConsentBridgeConfig?

        init(onChange: @escaping ([String]) -> Void) {
            self.onChange = onChange
        }

        func load(into webView: WKWebView, config: ConsentBridgeConfig) {
            lastLoadedConfig = config
            guard let widgetJSURL = Bundle.module.url(forResource: "dpdp-consent-widget", withExtension: "js"),
                  let widgetJS = try? String(contentsOf: widgetJSURL, encoding: .utf8) else {
                assertionFailure(
                    "ConsentBridgeWidget: dpdp-consent-widget.js not found in the app bundle. " +
                    "Add it to your target's Copy Bundle Resources build phase."
                )
                return
            }

            let encoder = JSONEncoder()
            guard let configData = try? encoder.encode(config),
                  let configJSON = String(data: configData, encoding: .utf8) else {
                assertionFailure("ConsentBridgeWidget: failed to encode config to JSON.")
                return
            }

            let html = """
            <!doctype html><html><head>
            <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
            <style>html,body{margin:0;padding:12px;background:transparent;}</style>
            </head><body>
            <div id="dpdp-consent-mount"></div>
            <script>\(widgetJS)</script>
            <script>
              DPDPConsentWidget.render(document.getElementById('dpdp-consent-mount'), Object.assign(
                \(configJSON),
                {
                  onChange: function (granted) {
                    window.webkit.messageHandlers.consentBridge.postMessage(granted);
                  }
                }
              ));
            </script>
            </body></html>
            """
            webView.loadHTMLString(html, baseURL: nil)
        }

        // MARK: WKScriptMessageHandler

        public func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "consentBridge", let granted = message.body as? [String] else { return }
            DispatchQueue.main.async {
                self.onChange(granted)
            }
        }
    }
}

extension ConsentBridgeConfig: Equatable {
    public static func == (lhs: ConsentBridgeConfig, rhs: ConsentBridgeConfig) -> Bool {
        (try? JSONEncoder().encode(lhs)) == (try? JSONEncoder().encode(rhs))
    }
}
