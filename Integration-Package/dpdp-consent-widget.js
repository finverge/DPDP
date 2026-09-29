/*!
 * ConsentBridge Widget — Finverge's DPDP Compliance Platform (BRD P360-06:
 * "Embeddable SDK for granular consent UI"; FSD Sec. 5.2).
 *
 * A single dependency-free file. No React, no build step, no framework
 * requirement — any third-party app (React, Vue, plain HTML/PHP/Django
 * template, whatever) integrates it the same way:
 *
 *   <div id="dpdp-consent"></div>
 *   <script src="dpdp-consent-widget.js"></script>
 *   <script>
 *     DPDPConsentWidget.render(document.getElementById('dpdp-consent'), {
 *       apiBaseUrl: 'https://consent.example.com',
 *       tenantId: 'acme-fintech',
 *       dataPrincipalId: 'user-123',
 *       language: 'English',
 *       purposes: [
 *         { key: 'kyc', label: 'KYC & loan processing', required: true,
 *           grants: [{ data_category: 'PAN & Identity', purpose: 'KYC & loan processing' }] },
 *         { key: 'marketing', label: 'Marketing communications', required: false,
 *           grants: [{ data_category: 'Contact Details', purpose: 'Marketing / cross-sell communications', duration_days: 365 }] },
 *       ],
 *       theme: { primaryColor: '#0B5FFF', radius: '10px', fontFamily: 'inherit' },
 *       onComplete: (grantedPurposeKeys) => console.log('granted:', grantedPurposeKeys),
 *     })
 *   </script>
 *
 * Every visual choice is a CSS custom property (--dpdp-*) with a sane
 * default, scoped under one root class (.dpdp-consent-widget) so this can
 * never leak into, or be clobbered by, the host page's own styles — the
 * whole point of something meant to sit inside someone else's app (BRD
 * Sec. 8's white-label model).
 *
 * Talks directly to the DPDP Compliance Platform's public REST API
 * (GET /notices/current, POST /consents/capture, POST /consents/:id/withdraw)
 * — the exact same endpoints Finverge's own diy-portal calls via
 * lib/dpdpApi.ts, proving this is genuinely one platform serving both an
 * internal and a third-party integration, not two implementations.
 */
(function (global) {
  "use strict";

  var STYLE_ID = "dpdp-consent-widget-styles";

  function injectStylesOnce() {
    if (document.getElementById(STYLE_ID)) return;
    var style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = [
      // Visual system defaults per the product's design guideline: primary
      // blue #1E88E5, teal accent #26A69A, light gray #ECEFF1 — Inter/
      // Montserrat preferred where already installed on the host system
      // (no Google Fonts network call from inside a zero-dependency
      // widget; a host page that already loads those fonts gets them for
      // free via this stack, everyone else gets a clean system fallback).
      ".dpdp-consent-widget{",
      "  --dpdp-primary:#1E88E5; --dpdp-accent:#26A69A; --dpdp-primary-fg:#ffffff; --dpdp-border:#E2E5EA;",
      "  --dpdp-bg:#ffffff; --dpdp-bg-muted:#ECEFF1; --dpdp-text:#1B2530; --dpdp-text-muted:#6B7684;",
      // Deliberately separate from --dpdp-text: the notice callout keeps
      // its own light bg-muted card regardless of an integrator's page-
      // level dark theme (applyTheme only ever overrides --dpdp-text, not
      // this), so its title needs a color guaranteed to contrast against
      // THAT background, not whatever the page's text color happens to
      // be — a real contrast bug caught by visual QA against demo.html's
      // dark theme, not a hypothetical one.
      "  --dpdp-bg-muted-fg:#1B2530;",
      "  --dpdp-danger:#D6394A; --dpdp-radius:10px;",
      "  --dpdp-font:Inter,Montserrat,-apple-system,'Segoe UI',Roboto,sans-serif; --dpdp-font-size:14px;",
      "  font-family:var(--dpdp-font); font-size:var(--dpdp-font-size); color:var(--dpdp-text);",
      "  background:var(--dpdp-bg); border:1px solid var(--dpdp-border); border-radius:var(--dpdp-radius);",
      "  padding:16px; max-width:480px; box-sizing:border-box; position:relative;",
      "}",
      "@media (prefers-color-scheme: dark){",
      "  .dpdp-consent-widget:not([data-dpdp-theme-locked]){",
      "    --dpdp-bg:#161B22; --dpdp-bg-muted:#20262E; --dpdp-text:#E7ECF1; --dpdp-text-muted:#9AA7B4; --dpdp-border:#2B333D;",
      "    --dpdp-bg-muted-fg:#E7ECF1;",
      "  }",
      "}",
      ".dpdp-consent-widget *{box-sizing:border-box;}",
      ".dpdp-cw-notice{background:var(--dpdp-bg-muted); border:1px solid var(--dpdp-border); border-radius:calc(var(--dpdp-radius) - 4px); padding:12px; margin-bottom:14px;}",
      ".dpdp-cw-notice-title{font-weight:600; font-size:13px; margin-bottom:6px; display:flex; align-items:center; gap:6px; color:var(--dpdp-bg-muted-fg);}",
      ".dpdp-cw-notice-body{font-size:12.5px; color:var(--dpdp-text-muted); white-space:pre-line; max-height:140px; overflow-y:auto; line-height:1.5;}",
      ".dpdp-cw-purpose{border:1px solid var(--dpdp-border); border-radius:calc(var(--dpdp-radius) - 4px); padding:12px; margin-bottom:10px; transition:border-color .15s ease, background-color .15s ease;}",
      ".dpdp-cw-purpose:has(input:checked){border-color:var(--dpdp-primary);}",
      ".dpdp-cw-purpose-row{display:flex; align-items:flex-start; gap:10px; cursor:pointer;}",
      ".dpdp-cw-purpose-row input{margin-top:3px; width:16px; height:16px; accent-color:var(--dpdp-primary); flex-shrink:0;}",
      ".dpdp-cw-purpose-label{font-size:13.5px; line-height:1.4;}",
      ".dpdp-cw-required{color:var(--dpdp-danger);}",
      // Progressive disclosure: itemised data categories start collapsed —
      // purpose + a one-line summary is the essential info shown first;
      // "Details" expands the per-field breakdown, never the reverse.
      ".dpdp-cw-details-toggle{background:none; border:none; padding:0; margin:4px 0 0 26px; font-size:11.5px; color:var(--dpdp-primary); cursor:pointer; text-decoration:underline; text-underline-offset:2px; font-family:inherit;}",
      ".dpdp-cw-items{margin:6px 0 0 26px; padding:0; list-style:none; font-size:12px; color:var(--dpdp-text-muted); display:none;}",
      ".dpdp-cw-items.open{display:block;}",
      ".dpdp-cw-items li{padding:1px 0;}",
      ".dpdp-cw-footer{margin-top:4px; font-size:11px; color:var(--dpdp-text-muted); display:flex; justify-content:space-between; align-items:center;}",
      ".dpdp-cw-badge{font-size:11px; padding:2px 7px; border-radius:999px; background:var(--dpdp-bg-muted); color:var(--dpdp-text-muted); transition:background-color .15s ease, color .15s ease;}",
      ".dpdp-cw-badge.granted{background:color-mix(in srgb, var(--dpdp-accent) 18%, white); color:var(--dpdp-accent);}",
      ".dpdp-cw-error{color:var(--dpdp-danger); font-size:12.5px; margin:8px 0;}",
      ".dpdp-cw-loading{color:var(--dpdp-text-muted); font-size:12.5px;}",
      // Toast feedback (interaction pattern guideline) — one at a time,
      // bottom-anchored inside the widget's own box so it never escapes
      // the scoped root or overlaps host-page chrome.
      ".dpdp-cw-toast{position:absolute; left:16px; right:16px; bottom:-14px; transform:translateY(0); background:var(--dpdp-text); color:var(--dpdp-bg); font-size:12px; padding:8px 12px; border-radius:8px; opacity:0; pointer-events:none; transition:opacity .2s ease, transform .2s ease; box-shadow:0 4px 12px rgba(0,0,0,.15);}",
      ".dpdp-cw-toast.show{opacity:1; transform:translateY(-8px);}",
    ].join("\n");
    document.head.appendChild(style);
  }

  function el(tag, className, html) {
    var e = document.createElement(tag);
    if (className) e.className = className;
    if (html != null) e.innerHTML = html;
    return e;
  }

  function applyTheme(root, theme) {
    theme = theme || {};
    var map = {
      primaryColor: "--dpdp-primary", accentColor: "--dpdp-accent", radius: "--dpdp-radius",
      fontFamily: "--dpdp-font", fontSize: "--dpdp-font-size",
      background: "--dpdp-bg", textColor: "--dpdp-text",
      // Optional — an integrator on a dark page may want the notice
      // callout to match rather than stay a light card (both are valid;
      // the un-set default is deliberately guaranteed-contrast-safe, see
      // --dpdp-bg-muted-fg's comment above).
      mutedBackground: "--dpdp-bg-muted", mutedTextColor: "--dpdp-bg-muted-fg",
    };
    Object.keys(map).forEach(function (k) {
      if (theme[k]) root.style.setProperty(map[k], theme[k]);
    });
    // An integrator who explicitly sets background/textColor has opted
    // into a specific look (e.g. demo.html's dark host page) — the
    // prefers-color-scheme dark-mode default must not silently override
    // that choice, only fill in when nothing explicit was given.
    if (theme.background || theme.textColor) root.setAttribute("data-dpdp-theme-locked", "");
  }

  function showToast(root, message) {
    var toast = root.querySelector(".dpdp-cw-toast");
    if (!toast) {
      toast = el("div", "dpdp-cw-toast");
      root.appendChild(toast);
    }
    toast.textContent = message;
    // Restart the transition even if a toast is already mid-fade.
    toast.classList.remove("show");
    void toast.offsetWidth;
    toast.classList.add("show");
    clearTimeout(toast._hideTimer);
    toast._hideTimer = setTimeout(function () { toast.classList.remove("show"); }, 2400);
  }

  async function api(baseUrl, path, options) {
    var res = await fetch(baseUrl + path, Object.assign({
      headers: { "Content-Type": "application/json" },
    }, options || {}));
    if (!res.ok) {
      var body = await res.json().catch(function () { return { detail: res.statusText }; });
      var err = new Error(Array.isArray(body.detail) ? body.detail.map(function (d) { return d.msg; }).join("; ") : body.detail);
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  function render(container, config) {
    if (!container) throw new Error("DPDPConsentWidget.render: a mount element is required.");
    if (!config || !config.apiBaseUrl || !config.tenantId || !config.dataPrincipalId || !config.purposes) {
      throw new Error("DPDPConsentWidget.render: apiBaseUrl, tenantId, dataPrincipalId and purposes are required.");
    }
    injectStylesOnce();

    var language = config.language || "English";
    var root = el("div", "dpdp-consent-widget");
    applyTheme(root, config.theme);
    container.innerHTML = "";
    container.appendChild(root);

    // Phase 2 white-label: autoTheme fetches the tenant's own registered
    // branding (GET /tenants/{id}, set via PUT /tenants/{id}/branding) and
    // applies it on top of any explicit `theme` config — the tenant's own
    // dashboard-configured colors win over a hardcoded integration
    // default, without the integrator having to hand-copy brand values
    // into every embed. Requires config.tenantId to be a real Tenant
    // registry id (POST /tenants), not just the loose tenant_id string
    // Phase 1's notice/consent endpoints accept — see README "Phase 1 vs
    // Phase 2 tenant identity" note.
    if (config.autoTheme) {
      api(config.apiBaseUrl, "/tenants/" + encodeURIComponent(config.tenantId), {})
        .then(function (tenant) {
          applyTheme(root, {
            primaryColor: tenant.brand_primary_color || undefined,
            fontFamily: tenant.brand_font_family || undefined,
          });
        })
        .catch(function () { /* no registered tenant/branding yet — explicit theme (if any) stands */ });
    }

    var noticeBox = el("div", "dpdp-cw-notice");
    noticeBox.appendChild(el("div", "dpdp-cw-notice-title", "\u{1F6E1}\u{FE0F} How your data is used"));
    var noticeBody = el("div", "dpdp-cw-loading", "Loading privacy notice…");
    noticeBox.appendChild(noticeBody);
    root.appendChild(noticeBox);

    var errorBox = el("div", "dpdp-cw-error");
    errorBox.style.display = "none";
    root.appendChild(errorBox);

    var purposeState = {}; // key -> { granted: bool, records: [], el, checkbox }
    var currentNotice = null;

    function showError(msg) {
      errorBox.textContent = msg;
      errorBox.style.display = msg ? "block" : "none";
    }

    function buildPurposeRow(purpose) {
      var box = el("div", "dpdp-cw-purpose");
      var row = el("label", "dpdp-cw-purpose-row");
      var checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.disabled = true; // enabled once notice loads
      var labelSpan = el("span", "dpdp-cw-purpose-label",
        purpose.label + (purpose.required ? ' <span class="dpdp-cw-required">*</span>' : " (optional)"));
      row.appendChild(checkbox);
      row.appendChild(labelSpan);
      box.appendChild(row);

      // Progressive disclosure: purpose + a plain-language one-liner is
      // the essential info shown up front; the per-field breakdown is a
      // click away, not pre-expanded clutter.
      if (purpose.grants.length > 1) {
        var toggle = el("button", "dpdp-cw-details-toggle", "Details");
        toggle.type = "button";
        var ul = el("ul", "dpdp-cw-items");
        purpose.grants.forEach(function (g) { ul.appendChild(el("li", null, "· " + g.data_category)); });
        toggle.addEventListener("click", function () {
          var open = ul.classList.toggle("open");
          toggle.textContent = open ? "Hide details" : "Details";
        });
        box.appendChild(toggle);
        box.appendChild(ul);
      }

      var footer = el("div", "dpdp-cw-footer");
      var badge = el("span", "dpdp-cw-badge", "Not granted");
      footer.appendChild(badge);
      box.appendChild(footer);

      checkbox.addEventListener("change", function () {
        handleToggle(purpose, checkbox.checked);
      });

      purposeState[purpose.key] = { granted: false, records: [], checkbox: checkbox, badge: badge };
      return box;
    }

    var purposesContainer = el("div");
    config.purposes.forEach(function (p) { purposesContainer.appendChild(buildPurposeRow(p)); });
    root.appendChild(purposesContainer);

    async function handleToggle(purpose, checked) {
      var state = purposeState[purpose.key];
      showError("");
      state.checkbox.disabled = true;
      try {
        if (checked) {
          var records = await api(config.apiBaseUrl, "/consents/capture", {
            method: "POST",
            body: JSON.stringify({
              tenant_id: config.tenantId, data_principal_id: config.dataPrincipalId,
              notice_id: currentNotice.id, language: currentNotice.language, grants: purpose.grants,
            }),
          });
          state.records = records;
          state.granted = true;
          state.badge.textContent = "Granted";
          state.badge.classList.add("granted");
          showToast(root, "Consent updated — sharing for " + purpose.label.toLowerCase() + ".");
        } else {
          await Promise.all(state.records.map(function (r) {
            return api(config.apiBaseUrl, "/consents/" + r.id + "/withdraw", {
              method: "POST", body: JSON.stringify({ actor: config.dataPrincipalId }),
            });
          }));
          state.records = [];
          state.granted = false;
          state.badge.textContent = "Not granted";
          state.badge.classList.remove("granted");
          showToast(root, "Consent withdrawn for " + purpose.label.toLowerCase() + ".");
        }
        if (typeof config.onChange === "function") {
          config.onChange(Object.keys(purposeState).filter(function (k) { return purposeState[k].granted; }));
        }
      } catch (err) {
        checked ? (state.checkbox.checked = false) : (state.checkbox.checked = true);
        showError(err.message || "Could not record your consent. Please try again.");
      } finally {
        state.checkbox.disabled = false;
      }
    }

    // Load the notice — nothing is selectable until it loads (§5: notice
    // must precede/accompany the request), same rule as diy-portal's
    // native integration (lib/dpdpApi.ts + ConsentStep.tsx).
    (async function loadNotice() {
      try {
        currentNotice = await api(config.apiBaseUrl,
          "/notices/current?tenant_id=" + encodeURIComponent(config.tenantId) + "&language=" + encodeURIComponent(language));
      } catch (err) {
        if (err.status === 404 && language !== "English") {
          try {
            currentNotice = await api(config.apiBaseUrl,
              "/notices/current?tenant_id=" + encodeURIComponent(config.tenantId) + "&language=English");
            noticeBody.textContent = "";
          } catch (err2) {
            noticeBody.textContent = "Privacy notice unavailable right now.";
            showError("Consent cannot be captured until the privacy notice loads. Please retry shortly.");
            return;
          }
        } else {
          noticeBody.textContent = "Privacy notice unavailable right now.";
          showError("Consent cannot be captured until the privacy notice loads. Please retry shortly.");
          return;
        }
      }
      noticeBody.className = "dpdp-cw-notice-body";
      noticeBody.textContent = currentNotice.content;
      Object.keys(purposeState).forEach(function (k) { purposeState[k].checkbox.disabled = false; });
    })();

    return {
      /** Returns the purpose keys currently granted — poll or call after onChange. */
      getGrantedPurposes: function () {
        return Object.keys(purposeState).filter(function (k) { return purposeState[k].granted; });
      },
      destroy: function () { container.innerHTML = ""; },
    };
  }

  global.DPDPConsentWidget = { render: render };
})(window);
