import { jsx as _jsx } from "react/jsx-runtime";
import { useEffect, useRef } from "react";
/**
 * React wrapper around the vanilla-JS ConsentBridge widget
 * (@consentbridge/consent-widget). Mounts the underlying widget into a
 * ref'd div, tears it down on unmount, and re-mounts if apiBaseUrl,
 * tenantId, dataPrincipalId, language, autoTheme, purposes, or theme
 * actually change (the underlying widget has no partial-update API, so
 * a changed config gets a fresh render rather than an attempted diff —
 * simpler than guessing which fields it would tolerate mutating in
 * place, and correct given how rarely those fields change after mount).
 *
 * onChange is deliberately NOT one of the remount triggers: a caller
 * passing a fresh arrow function every render (the common case) must
 * not force a widget remount every render. Instead the latest onChange
 * is tracked in a ref and always called through a stable wrapper, so it
 * can change freely across renders without ever going stale or causing
 * a remount.
 *
 * Requires window.DPDPConsentWidget to already be defined — either via
 * <script src="https://your-cdn/dpdp-consent-widget.js"> in your HTML,
 * or by importing "@consentbridge/consent-widget/register" once at your
 * app's entry point (see that package's README).
 */
export function ConsentWidget({ className, style, onChange, ...config }) {
    const containerRef = useRef(null);
    const handleRef = useRef(null);
    const onChangeRef = useRef(onChange);
    onChangeRef.current = onChange;
    const purposesKey = JSON.stringify(config.purposes);
    const themeKey = JSON.stringify(config.theme);
    useEffect(() => {
        const widget = window.DPDPConsentWidget;
        if (!widget) {
            // eslint-disable-next-line no-console
            console.error("@consentbridge/react: window.DPDPConsentWidget is not defined. Load dpdp-consent-widget.js " +
                "via a <script> tag, or `import \"@consentbridge/consent-widget/register\"` once at your app's entry point.");
            return;
        }
        if (!containerRef.current)
            return;
        handleRef.current = widget.render(containerRef.current, {
            ...config,
            onChange: (grantedPurposeKeys) => onChangeRef.current?.(grantedPurposeKeys),
        });
        return () => {
            handleRef.current?.destroy();
            handleRef.current = null;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [
        config.apiBaseUrl,
        config.tenantId,
        config.dataPrincipalId,
        config.language,
        config.autoTheme,
        purposesKey,
        themeKey,
    ]);
    return _jsx("div", { ref: containerRef, className: className, style: style });
}
