// ConsentBridgeWidgetView.kt
//
// A thin WebView wrapper around the SAME dpdp-consent-widget.js this SDK
// ships for web — deliberately NOT a native re-implementation of the
// consent-capture UI. Every purpose toggle, notice fetch, and
// /consents/capture call runs inside the WebView, running the exact
// widget code the web and React integrations run, so there is one real
// compliance implementation behind all three, not three to keep in sync.
//
// HONEST STATUS: written against the current, stable android.webkit
// WebView APIs, but this Windows dev environment has no JDK/Android
// SDK/Gradle toolchain — it could not be compiled or run here (confirmed:
// no `java`, `kotlinc`, `gradle` available). Treat this as a careful
// first draft to compile and smoke-test in a real Android Studio project
// before shipping, the same "flagged, not silently passed off as
// verified" discipline this whole SDK follows for anything not actually run.
//
// Zero external dependencies by design (matches the web widget) — JSON
// is built/parsed with org.json, which ships with the Android platform.

package com.finverge.consentbridge

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.util.AttributeSet
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.widget.FrameLayout
import org.json.JSONArray
import org.json.JSONObject

data class ConsentGrant(
    val dataCategory: String,
    val purpose: String,
    val durationDays: Int? = null,
)

data class ConsentPurpose(
    val key: String,
    val label: String,
    val required: Boolean,
    val grants: List<ConsentGrant>,
)

data class ConsentTheme(
    val primaryColor: String? = null,
    val accentColor: String? = null,
    val radius: String? = null,
    val fontFamily: String? = null,
    val fontSize: String? = null,
    val background: String? = null,
    val textColor: String? = null,
    val mutedBackground: String? = null,
    val mutedTextColor: String? = null,
    val mutedForegroundColor: String? = null,
    val accentTextColor: String? = null,
)

data class ConsentBridgeConfig(
    val apiBaseUrl: String,
    val tenantId: String,
    val dataPrincipalId: String,
    val language: String = "English",
    val purposes: List<ConsentPurpose>,
    val theme: ConsentTheme? = null,
    val autoTheme: Boolean? = null,
)

/**
 * Drop-in Android View. Usage:
 * ```
 * val widget = ConsentBridgeWidgetView(context)
 * widget.onChange = { granted -> ... }
 * widget.load(config)
 * parentLayout.addView(widget)
 * ```
 */
@SuppressLint("SetJavaScriptEnabled")
class ConsentBridgeWidgetView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : FrameLayout(context, attrs) {

    /** Called on the main thread with the currently granted purpose keys, after every grant/withdraw. */
    var onChange: ((List<String>) -> Unit)? = null

    private val webView: WebView = WebView(context).apply {
        settings.javaScriptEnabled = true
        setBackgroundColor(Color.TRANSPARENT)
        addJavascriptInterface(Bridge(), "ConsentBridgeAndroid")
    }

    init {
        addView(webView)
    }

    fun load(config: ConsentBridgeConfig) {
        val widgetJs = context.assets.open("dpdp-consent-widget.js")
            .bufferedReader(Charsets.UTF_8).use { it.readText() }
        val configJson = config.toJson()

        val html = """
            <!doctype html><html><head>
            <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
            <style>html,body{margin:0;padding:12px;background:transparent;}</style>
            </head><body>
            <div id="dpdp-consent-mount"></div>
            <script>$widgetJs</script>
            <script>
              DPDPConsentWidget.render(document.getElementById('dpdp-consent-mount'), Object.assign(
                $configJson,
                {
                  onChange: function (granted) {
                    ConsentBridgeAndroid.onConsentChange(JSON.stringify(granted));
                  }
                }
              ));
            </script>
            </body></html>
        """.trimIndent()

        // baseURL "https://consentbridge.local/" (not a real host — never
        // resolved) rather than null: some WebView versions restrict
        // fetch()/XHR from a null-origin page more aggressively than from
        // a same-scheme http(s) origin, and the widget's own fetch calls
        // go to config.apiBaseUrl regardless of this page's own origin.
        webView.loadDataWithBaseURL("https://consentbridge.local/", html, "text/html", "UTF-8", null)
    }

    /** Tears down the WebView. Call from onDetachedFromWindow / your Fragment's onDestroyView. */
    fun destroy() {
        webView.removeJavascriptInterface("ConsentBridgeAndroid")
        webView.destroy()
    }

    private inner class Bridge {
        @JavascriptInterface
        fun onConsentChange(grantedJson: String) {
            val array = JSONArray(grantedJson)
            val granted = (0 until array.length()).map { array.getString(it) }
            post { onChange?.invoke(granted) } // hop back onto the main thread — JS interface callbacks arrive off it
        }
    }
}

private fun ConsentGrant.toJson(): JSONObject = JSONObject().apply {
    put("data_category", dataCategory)
    put("purpose", purpose)
    durationDays?.let { put("duration_days", it) }
}

private fun ConsentPurpose.toJson(): JSONObject = JSONObject().apply {
    put("key", key)
    put("label", label)
    put("required", required)
    put("grants", JSONArray(grants.map { it.toJson() }))
}

private fun ConsentTheme.toJson(): JSONObject = JSONObject().apply {
    primaryColor?.let { put("primaryColor", it) }
    accentColor?.let { put("accentColor", it) }
    radius?.let { put("radius", it) }
    fontFamily?.let { put("fontFamily", it) }
    fontSize?.let { put("fontSize", it) }
    background?.let { put("background", it) }
    textColor?.let { put("textColor", it) }
    mutedBackground?.let { put("mutedBackground", it) }
    mutedTextColor?.let { put("mutedTextColor", it) }
    mutedForegroundColor?.let { put("mutedForegroundColor", it) }
    accentTextColor?.let { put("accentTextColor", it) }
}

private fun ConsentBridgeConfig.toJson(): String = JSONObject().apply {
    put("apiBaseUrl", apiBaseUrl)
    put("tenantId", tenantId)
    put("dataPrincipalId", dataPrincipalId)
    put("language", language)
    put("purposes", JSONArray(purposes.map { it.toJson() }))
    theme?.let { put("theme", it.toJson()) }
    autoTheme?.let { put("autoTheme", it) }
}.toString()
