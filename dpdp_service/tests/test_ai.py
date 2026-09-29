"""Phase 3 — deterministic AI-native capability layer (app/ai.py, routes_ai.py)."""


def _approved_notice(client, auth_headers, tenant_id, language="English", content="notice text"):
    headers = auth_headers(tenant_id)
    draft = client.post("/notices", json={"tenant_id": tenant_id, "language": language, "content": content}, headers=headers).json()
    client.post(f"/notices/{draft['id']}/approve", json={"approved_by": "dpo"}, headers=headers)
    return draft["id"]


# ---------------------------------------------------------------------- #
# Consent-Purpose Drift Detector
# ---------------------------------------------------------------------- #
def test_masking_apply_without_data_principal_id_never_flags_drift(client, auth_headers):
    client.put("/masking/policies", json={
        "tenant_id": "ai1", "purpose": "csv_export", "created_by": "a", "field_rules": {"x": "allow"},
    }, headers=auth_headers("ai1"))
    client.post("/masking/apply", json={
        "tenant_id": "ai1", "purpose": "csv_export", "actor": "analyst", "records": [{"x": "1"}],
    })
    flags = client.get("/ai/drift-flags", params={"tenant_id": "ai1"}, headers=auth_headers("ai1")).json()
    assert flags == []


def test_masking_apply_with_consented_purpose_does_not_flag_drift(client, auth_headers):
    notice_id = _approved_notice(client, auth_headers, "ai2")
    client.post("/consents/capture", json={
        "tenant_id": "ai2", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "profile_export"}],
    })
    client.put("/masking/policies", json={
        "tenant_id": "ai2", "purpose": "profile_export", "created_by": "a", "field_rules": {"PAN": "redact"},
    }, headers=auth_headers("ai2"))
    client.post("/masking/apply", json={
        "tenant_id": "ai2", "purpose": "profile_export", "actor": "svc", "data_principal_id": "dp1",
        "records": [{"PAN": "ABCDE1234F"}],
    })
    flags = client.get("/ai/drift-flags", params={"tenant_id": "ai2"}, headers=auth_headers("ai2")).json()
    assert flags == []


def test_masking_apply_for_uncomsented_purpose_flags_drift(client, auth_headers):
    client.put("/masking/policies", json={
        "tenant_id": "ai3", "purpose": "marketing_export", "created_by": "a", "field_rules": {"email": "allow"},
    }, headers=auth_headers("ai3"))
    client.post("/masking/apply", json={
        "tenant_id": "ai3", "purpose": "marketing_export", "actor": "svc", "data_principal_id": "dp1",
        "records": [{"email": "a@b.com"}],
    })
    flags = client.get("/ai/drift-flags", params={"tenant_id": "ai3"}, headers=auth_headers("ai3")).json()
    assert len(flags) == 1
    assert flags[0]["purpose"] == "marketing_export"
    assert flags[0]["data_principal_id"] == "dp1"


def test_withdrawn_consent_still_flags_drift_on_reuse(client, auth_headers):
    notice_id = _approved_notice(client, auth_headers, "ai4")
    captured = client.post("/consents/capture", json={
        "tenant_id": "ai4", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "profile_export"}],
    }).json()
    client.post(f"/consents/{captured[0]['id']}/withdraw", json={"actor": "dp1"})

    client.put("/masking/policies", json={
        "tenant_id": "ai4", "purpose": "profile_export", "created_by": "a", "field_rules": {"PAN": "redact"},
    }, headers=auth_headers("ai4"))
    client.post("/masking/apply", json={
        "tenant_id": "ai4", "purpose": "profile_export", "actor": "svc", "data_principal_id": "dp1",
        "records": [{"PAN": "X"}],
    })
    flags = client.get("/ai/drift-flags", params={"tenant_id": "ai4"}, headers=auth_headers("ai4")).json()
    assert len(flags) == 1


# ---------------------------------------------------------------------- #
# Breach-Risk Early-Warning
# ---------------------------------------------------------------------- #
def test_breach_risk_score_rises_with_drift_and_blocks(client, auth_headers):
    headers = auth_headers("ai5")
    baseline = client.get("/ai/breach-risk", params={"tenant_id": "ai5"}, headers=headers).json()
    assert baseline["score"] == 0
    assert baseline["band"] == "low"

    # one drift flag
    client.put("/masking/policies", json={
        "tenant_id": "ai5", "purpose": "p1", "created_by": "a", "field_rules": {"x": "allow"},
    }, headers=headers)
    client.post("/masking/apply", json={
        "tenant_id": "ai5", "purpose": "p1", "actor": "svc", "data_principal_id": "dp1", "records": [{"x": "1"}],
    })
    # one masking block (no policy for a different purpose)
    client.post("/masking/apply", json={
        "tenant_id": "ai5", "purpose": "no_such_purpose", "actor": "svc", "records": [{"x": "1"}],
    })

    after = client.get("/ai/breach-risk", params={"tenant_id": "ai5"}, headers=headers).json()
    assert after["score"] > 0
    assert after["factors"]["drift_flags"] == 1
    assert after["factors"]["masking_blocks"] == 1


# ---------------------------------------------------------------------- #
# Plain-Language Notice Generator
# ---------------------------------------------------------------------- #
def test_ai_draft_notice_creates_a_draft_not_auto_approved(client, auth_headers):
    resp = client.post("/ai/draft-notice", json={
        "tenant_id": "ai6", "language": "English",
        "purposes": [{"purpose": "KYC & loan processing", "data_categories": ["PAN", "Address Proof"]}],
    }, headers=auth_headers("ai6"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    assert "PAN, Address Proof" in body["content"]
    assert "KYC & loan processing" in body["content"]

    # not usable for capture until a DPO approves it
    current = client.get("/notices/current", params={"tenant_id": "ai6", "language": "English"})
    assert current.status_code == 404


# ---------------------------------------------------------------------- #
# DPIA Co-Pilot
# ---------------------------------------------------------------------- #
def test_dpia_draft_is_immutable_snapshot_history(client, auth_headers):
    notice_id = _approved_notice(client, auth_headers, "ai7")
    client.post("/consents/capture", json={
        "tenant_id": "ai7", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    })
    headers = auth_headers("ai7", role="dpo")

    first = client.post("/ai/draft-dpia/ai7", params={"generated_by": "dpo_1"}, headers=headers).json()
    assert first["snapshot_json"]["active_consent_count"] == 1
    assert "PAN" in first["snapshot_json"]["data_categories_processed"]

    second = client.post("/ai/draft-dpia/ai7", params={"generated_by": "dpo_1"}, headers=headers).json()
    assert second["id"] != first["id"]

    latest = client.get("/ai/dpia/ai7", headers=headers).json()
    assert latest["id"] == second["id"]

    history = client.get("/ai/dpia/ai7/history", headers=headers).json()
    assert len(history) == 2


def test_dpia_404_when_none_generated(client, auth_headers):
    resp = client.get("/ai/dpia/never-generated", headers=auth_headers("never-generated"))
    assert resp.status_code == 404


# ---------------------------------------------------------------------- #
# Grievance Triage & Draft-Response
# ---------------------------------------------------------------------- #
def test_triage_flags_repeat_subject_as_frivolous_signal(client, auth_headers):
    tid = "ai8"
    for _ in range(3):
        g = client.post("/grievances", json={
            "tenant_id": tid, "data_principal_id": "dp1", "category": "Other", "subject": "Same complaint",
            "description": "repeat",
        }).json()
    triage = client.post(f"/ai/triage-grievance/{g['id']}", headers=auth_headers(tid, role="compliance_officer")).json()
    assert triage["frivolous_signal"] is True
    assert triage["suggested_severity"] == "medium"
    assert "Same complaint" in triage["draft_response"] or "complaint" in triage["draft_response"].lower()


def test_triage_high_severity_category(client, auth_headers):
    g = client.post("/grievances", json={
        "tenant_id": "ai9", "data_principal_id": "dp1", "category": "Consent / data use",
        "subject": "unique subject", "description": "x",
    }).json()
    headers = auth_headers("ai9", role="compliance_officer")
    triage = client.post(f"/ai/triage-grievance/{g['id']}", headers=headers).json()
    assert triage["suggested_severity"] == "high"
    assert triage["frivolous_signal"] is False

    # triage never resolves the grievance itself
    fetched = client.get(f"/grievances/{g['id']}", headers=headers).json()
    assert fetched["status"] == "Open"


def test_triage_404_for_unknown_grievance(client, auth_headers):
    resp = client.post("/ai/triage-grievance/no-such-id", headers=auth_headers("ai9b", role="compliance_officer"))
    assert resp.status_code == 404


# ---------------------------------------------------------------------- #
# Purpose-Gated Recommendation Engine (Data-Principal-facing — no auth)
# ---------------------------------------------------------------------- #
def test_cross_sell_only_returns_offers_with_full_consent_coverage(client, auth_headers):
    notice_id = _approved_notice(client, auth_headers, "ai10")
    client.post("/consents/capture", json={
        "tenant_id": "ai10", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [
            {"data_category": "Income", "purpose": "Marketing / cross-sell"},
            {"data_category": "Contact Details", "purpose": "Marketing / cross-sell"},
        ],
    })
    resp = client.post("/ai/cross-sell/candidates", json={
        "tenant_id": "ai10", "data_principal_id": "dp1",
        "catalog": [
            {"offer_id": "card1", "title": "Cashback Card", "purpose": "Marketing / cross-sell",
             "required_data_categories": ["Income", "Contact Details"]},
            {"offer_id": "insure1", "title": "Health Insurance", "purpose": "Marketing / cross-sell",
             "required_data_categories": ["Income", "Medical History"]},  # Medical History not consented
        ],
    })
    body = resp.json()
    ids = [o["offer_id"] for o in body]
    assert "card1" in ids
    assert "insure1" not in ids
    assert "why_you_are_seeing_this" in body[0]


def test_cross_sell_returns_empty_with_no_consent(client):
    resp = client.post("/ai/cross-sell/candidates", json={
        "tenant_id": "ai11", "data_principal_id": "dp-no-consent",
        "catalog": [{"offer_id": "x", "title": "X", "purpose": "Marketing", "required_data_categories": ["Income"]}],
    })
    assert resp.json() == []


# ---------------------------------------------------------------------- #
# Rights Assistant (structured Q&A, Data-Principal-facing — no auth)
# ---------------------------------------------------------------------- #
def test_rights_assistant_who_has_my_data(client, auth_headers):
    notice_id = _approved_notice(client, auth_headers, "ai12")
    client.post("/consents/capture", json={
        "tenant_id": "ai12", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    })
    resp = client.get("/ai/rights-assistant", params={
        "tenant_id": "ai12", "data_principal_id": "dp1", "question_type": "who_has_my_data",
    })
    assert resp.status_code == 200
    assert "KYC" in resp.json()["answer"]
    assert "PAN" in resp.json()["answer"]


def test_rights_assistant_no_data_case(client):
    resp = client.get("/ai/rights-assistant", params={
        "tenant_id": "ai13", "data_principal_id": "dp-none", "question_type": "who_has_my_data",
    })
    assert "don't currently have" in resp.json()["answer"]


def test_rights_assistant_unknown_question_type_is_422(client):
    resp = client.get("/ai/rights-assistant", params={
        "tenant_id": "ai14", "data_principal_id": "dp1", "question_type": "not_a_real_question",
    })
    assert resp.status_code == 422
