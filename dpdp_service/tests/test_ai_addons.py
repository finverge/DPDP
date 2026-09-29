"""AI Add-Ons (BRD Sec. 6.10-6.12): Consent Pattern Analytics, User
Sentiment & Trust Scoring, Automated Breach Simulation & Stress Testing."""
from datetime import datetime, timedelta, timezone


def _approved_notice(client, auth_headers, tenant_id, language="English", content="notice text"):
    headers = auth_headers(tenant_id)
    draft = client.post("/notices", json={"tenant_id": tenant_id, "language": language, "content": content}, headers=headers).json()
    client.post(f"/notices/{draft['id']}/approve", json={"approved_by": "dpo"}, headers=headers)
    return draft["id"]


# ---------------------------------------------------------------------- #
# Consent Pattern Analytics
# ---------------------------------------------------------------------- #
def test_consent_pattern_flags_purpose_with_high_withdrawal_rate(client, auth_headers):
    tid = "cpa1"
    notice_id = _approved_notice(client, auth_headers, tid)
    ids = []
    for i in range(6):
        captured = client.post("/consents/capture", json={
            "tenant_id": tid, "data_principal_id": f"dp{i}", "notice_id": notice_id,
            "grants": [{"data_category": "Email", "purpose": "marketing"}],
        }).json()
        ids.append(captured[0]["id"])
    for cid in ids[:4]:  # 4/6 withdrawn = 66% >= 50% threshold, sample >= 5
        client.post(f"/consents/{cid}/withdraw", json={"actor": "data_principal"})

    resp = client.get("/ai/consent-patterns", params={"tenant_id": tid}, headers=auth_headers(tid))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    marketing = next(p for p in body["purposes"] if p["purpose"] == "marketing")
    assert marketing["granted_count"] == 6
    assert marketing["withdrawn_count"] == 4
    assert marketing["flagged"] is True
    assert marketing["median_days_to_withdrawal"] is not None
    assert body["flagged_purpose_count"] == 1


def test_consent_pattern_below_min_sample_is_never_flagged(client, auth_headers):
    tid = "cpa2"
    notice_id = _approved_notice(client, auth_headers, tid)
    for i in range(2):
        captured = client.post("/consents/capture", json={
            "tenant_id": tid, "data_principal_id": f"dp{i}", "notice_id": notice_id,
            "grants": [{"data_category": "Email", "purpose": "newsletter"}],
        }).json()
        client.post(f"/consents/{captured[0]['id']}/withdraw", json={"actor": "data_principal"})

    body = client.get("/ai/consent-patterns", params={"tenant_id": tid}, headers=auth_headers(tid)).json()
    newsletter = next(p for p in body["purposes"] if p["purpose"] == "newsletter")
    assert newsletter["withdrawal_rate"] == 1.0
    assert newsletter["flagged"] is False  # 100% withdrawn but sample size below _MIN_SAMPLE


def test_consent_pattern_no_grants_yet_is_an_empty_purpose_list(client, auth_headers):
    tid = "cpa3"
    body = client.get("/ai/consent-patterns", params={"tenant_id": tid}, headers=auth_headers(tid)).json()
    assert body["purposes"] == []
    assert body["total_grants"] == 0


def test_consent_pattern_requires_auth(client):
    resp = client.get("/ai/consent-patterns", params={"tenant_id": "cpa4"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------- #
# User Sentiment & Trust Scoring
# ---------------------------------------------------------------------- #
def test_trust_score_with_no_grievances_is_none(client, auth_headers):
    tid = "ts1"
    body = client.get("/ai/trust-score", params={"tenant_id": tid}, headers=auth_headers(tid)).json()
    assert body["grievance_count"] == 0
    assert body["score"] is None
    assert body["band"] is None


def test_trust_score_reflects_negative_sentiment_and_resolution(client, auth_headers):
    tid = "ts2"
    headers = auth_headers(tid, role="compliance_officer")
    angry = client.post("/grievances", json={
        "tenant_id": tid, "data_principal_id": "dp1", "category": "Other", "subject": "furious",
        "description": "This is completely unacceptable, you shared my data without my consent and I am furious.",
    }).json()
    happy = client.post("/grievances", json={
        "tenant_id": tid, "data_principal_id": "dp2", "category": "Other", "subject": "thanks",
        "description": "Thank you so much, this was resolved quickly and I really appreciate the help.",
    }).json()
    client.post(f"/grievances/{happy['id']}/resolve", json={"resolved_by": "co1", "resolution_note": "done"}, headers=headers)

    body = client.get("/ai/trust-score", params={"tenant_id": tid}, headers=headers).json()
    assert body["grievance_count"] == 2
    assert body["score"] is not None
    per = {s["grievance_id"]: s for s in body["sentiment_by_grievance"]}
    assert per[angry["id"]]["band"] == "negative"
    assert per[happy["id"]]["band"] == "positive"
    assert body["resolution_rate"] == 0.5


def test_trust_score_requires_auth(client):
    resp = client.get("/ai/trust-score", params={"tenant_id": "ts3"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------- #
# Automated Breach Simulation & Stress Testing
# ---------------------------------------------------------------------- #
def test_breach_simulation_flags_masking_gap_and_missing_dpo_and_webhook(client, auth_headers):
    created = client.post("/tenants", json={"name": "BreachSim Co"}).json()
    tid = created["id"]
    headers = auth_headers(tid)

    notice_id = _approved_notice(client, auth_headers, tid)
    client.post("/consents/capture", json={
        "tenant_id": tid, "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    })
    # no masking policy for "KYC" yet, no DPO contact, no webhook subscription

    resp = client.post(f"/ai/breach-simulation/{tid}", params={"triggered_by": "dpo_1"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_id = {s["id"]: s for s in body["scenario_results_json"]}
    assert by_id["masking_coverage_gap"]["status"] == "fail"
    assert "KYC" in by_id["masking_coverage_gap"]["detail"]
    assert by_id["dpo_contact_published"]["status"] == "fail"
    assert by_id["breach_notification_wiring"]["status"] == "fail"
    assert by_id["api_key_exposure_window"]["status"] == "pass"  # freshly created, not due
    assert body["readiness_score"] < 100
    assert body["readiness_band"] in ("weak", "needs_attention")


def test_breach_simulation_score_improves_after_fixing_gaps(client, auth_headers):
    created = client.post("/tenants", json={"name": "BreachSim Fix Co"}).json()
    tid = created["id"]
    headers = auth_headers(tid)

    notice_id = _approved_notice(client, auth_headers, tid)
    client.post("/consents/capture", json={
        "tenant_id": tid, "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    })
    before = client.post(f"/ai/breach-simulation/{tid}", params={"triggered_by": "dpo_1"}, headers=headers).json()

    client.put("/masking/policies", json={
        "tenant_id": tid, "purpose": "KYC", "created_by": "a", "field_rules": {"PAN": "mask_last4"},
    }, headers=headers)
    client.put("/dpo-contact", json={"tenant_id": tid, "name": "DPO", "email": "dpo@example.com"}, headers=headers)
    client.post("/webhooks/subscriptions", json={
        "tenant_id": tid, "url": "https://example.com/hook", "events": ["breach.detected"], "created_by": "a",
    }, headers=headers)

    after = client.post(f"/ai/breach-simulation/{tid}", params={"triggered_by": "dpo_1"}, headers=headers).json()
    assert after["readiness_score"] > before["readiness_score"]
    by_id = {s["id"]: s for s in after["scenario_results_json"]}
    assert by_id["masking_coverage_gap"]["status"] == "pass"
    assert by_id["dpo_contact_published"]["status"] == "pass"
    assert by_id["breach_notification_wiring"]["status"] == "pass"
    assert after["readiness_band"] == "strong"


def test_breach_simulation_flags_overdue_grievance_backlog(client, auth_headers):
    from app.db import SessionLocal
    from app.models import Grievance

    created = client.post("/tenants", json={"name": "BacklogCo"}).json()
    tid = created["id"]
    headers = auth_headers(tid, role="compliance_officer")

    g = client.post("/grievances", json={
        "tenant_id": tid, "data_principal_id": "dp1", "category": "Other", "subject": "old", "description": "old one",
    }).json()

    db = SessionLocal()
    try:
        row = db.get(Grievance, g["id"])
        row.created_at = datetime.now(timezone.utc) - timedelta(days=45)
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/ai/breach-simulation/{tid}", params={"triggered_by": "co_1"}, headers=headers).json()
    by_id = {s["id"]: s for s in resp["scenario_results_json"]}
    assert by_id["grievance_sla_backlog"]["status"] == "warning"


def test_breach_simulation_history_and_latest(client, auth_headers):
    created = client.post("/tenants", json={"name": "HistCo"}).json()
    tid = created["id"]
    headers = auth_headers(tid)

    first = client.post(f"/ai/breach-simulation/{tid}", params={"triggered_by": "a"}, headers=headers).json()
    second = client.post(f"/ai/breach-simulation/{tid}", params={"triggered_by": "a"}, headers=headers).json()
    assert first["id"] != second["id"]

    latest = client.get(f"/ai/breach-simulation/{tid}", headers=headers).json()
    assert latest["id"] == second["id"]

    history = client.get(f"/ai/breach-simulation/{tid}/history", headers=headers).json()
    assert len(history) == 2


def test_breach_simulation_404_when_none_run_yet(client, auth_headers):
    created = client.post("/tenants", json={"name": "NoRunCo"}).json()
    resp = client.get(f"/ai/breach-simulation/{created['id']}", headers=auth_headers(created["id"]))
    assert resp.status_code == 404


def test_breach_simulation_requires_auth(client):
    resp = client.post("/ai/breach-simulation/some-tenant", params={"triggered_by": "x"})
    assert resp.status_code == 401
