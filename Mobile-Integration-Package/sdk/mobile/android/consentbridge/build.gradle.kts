// HONEST STATUS: not built/validated here — no JDK/Android SDK/Gradle
// toolchain in this dev environment (confirmed: no java/kotlinc/gradle).
// See ConsentBridgeWidgetView.kt's header comment.
plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.finverge.consentbridge"
    compileSdk = 34

    defaultConfig {
        minSdk = 21 // WKWebView-equivalent JS bridge (addJavascriptInterface) needs API 17+; 21 matches this SDK's own no-legacy-cruft baseline
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // Zero external dependencies by design — org.json and android.webkit
    // both ship with the platform. Deliberately not adding OkHttp,
    // Gson, etc.: the widget itself makes every network call from inside
    // the WebView via fetch(), same as the web/React integrations.
}
