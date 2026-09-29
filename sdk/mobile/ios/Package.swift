// swift-tools-version:5.7
// HONEST STATUS: not built/validated here — no Swift toolchain in this
// dev environment (confirmed: no swiftc/xcodebuild). See
// ConsentBridgeWidget.swift's header comment.
import PackageDescription

let package = Package(
    name: "ConsentBridgeWidget",
    platforms: [.iOS(.v14)],
    products: [
        .library(name: "ConsentBridgeWidget", targets: ["ConsentBridgeWidget"]),
    ],
    targets: [
        .target(
            name: "ConsentBridgeWidget",
            path: "Sources/ConsentBridgeWidget",
            resources: [.copy("dpdp-consent-widget.js")]
        ),
    ]
)
