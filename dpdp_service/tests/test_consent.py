"""Consent Management Engine — FSD Sec. 3."""


def _approve_new_notice(client, auth_headers, tenant_id="t1", language="en", content="Notice text v1") -> str:
    headers = auth_headers(tenant_id)
    draft = client.post("/notices", json={"tenant_id": tenant_id, "language": language, "content": content}, headers=headers)
    assert draft.status_code == 200, draft.text
    notice_id = draft.json()["id"]
    approve = client.post(f"/notices/{notice_id}/approve", json={"approved_by": "dpo_1"}, headers=headers)
    assert approve.status_code == 200, approve.text
    return notice_id


def test_current_notice_404_when_none_approved(client, auth_headers):
    resp = client.get("/notices/current", params={"tenant_id": "no-notice-tenant"})
    assert resp.status_code == 404


def test_draft_approve_and_fetch_current(client, auth_headers):
    notice_id = _approve_new_notice(client, auth_headers, tenant_id="t2")
    current = client.get("/notices/current", params={"tenant_id": "t2"})
    assert current.status_code == 200
    body = current.json()
    assert body["id"] == notice_id
    assert body["status"] == "approved"
    assert body["version"] == 1


def test_approving_a_new_version_retires_the_old_one(client, auth_headers):
    _approve_new_notice(client, auth_headers, tenant_id="t3", content="v1")
    notice_id_v2 = _approve_new_notice(client, auth_headers, tenant_id="t3", content="v2")
    current = client.get("/notices/current", params={"tenant_id": "t3"}).json()
    assert current["id"] == notice_id_v2
    assert current["version"] == 2


def test_double_approve_is_409(client, auth_headers):
    notice_id = _approve_new_notice(client, auth_headers, tenant_id="t4")
    resp = client.post(f"/notices/{notice_id}/approve", json={"approved_by": "dpo_1"}, headers=auth_headers("t4"))
    assert resp.status_code == 409


def test_capture_rejected_against_unapproved_notice(client, auth_headers):
    draft = client.post("/notices", json={"tenant_id": "t5", "language": "en", "content": "draft only"}, headers=auth_headers("t5"))
    notice_id = draft.json()["id"]
    resp = client.post("/consents/capture", json={
        "tenant_id": "t5", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    })
    assert resp.status_code == 422


def test_capture_rejects_empty_grants(client, auth_headers):
    notice_id = _approve_new_notice(client, auth_headers, tenant_id="t6")
    resp = client.post("/consents/capture", json={
        "tenant_id": "t6", "data_principal_id": "dp1", "notice_id": notice_id, "grants": [],
    })
    assert resp.status_code == 422


def test_capture_creates_one_record_per_grant_not_bundled(client, auth_headers):
    notice_id = _approve_new_notice(client, auth_headers, tenant_id="t7")
    resp = client.post("/consents/capture", json={
        "tenant_id": "t7", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [
            {"data_category": "PAN", "purpose": "KYC / loan processing"},
            {"data_category": "Address Proof", "purpose": "KYC / loan processing"},
            {"data_category": "Contact Details", "purpose": "Marketing / cross-sell", "duration_days": 365},
        ],
    })
    assert resp.status_code == 200, resp.text
    records = resp.json()
    assert len(records) == 3
    assert {r["data_category"] for r in records} == {"PAN", "Address Proof", "Contact Details"}
    assert all(r["withdrawn_at"] is None for r in records)


def test_withdraw_then_vault_reflects_it_and_double_withdraw_409(client, auth_headers):
    notice_id = _approve_new_notice(client, auth_headers, tenant_id="t8")
    captured = client.post("/consents/capture", json={
        "tenant_id": "t8", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "Bank Statement", "purpose": "Income verification"}],
    }).json()
    consent_id = captured[0]["id"]

    withdraw = client.post(f"/consents/{consent_id}/withdraw", json={"actor": "dp1", "reason": "changed my mind"})
    assert withdraw.status_code == 200
    assert withdraw.json()["withdrawn_at"] is not None

    second = client.post(f"/consents/{consent_id}/withdraw", json={"actor": "dp1"})
    assert second.status_code == 409

    vault = client.get("/consents", params={"tenant_id": "t8", "data_principal_id": "dp1"}).json()
    assert any(r["id"] == consent_id and r["withdrawn_at"] is not None for r in vault)


def test_withdrawing_one_purpose_does_not_affect_another(client, auth_headers):
    notice_id = _approve_new_notice(client, auth_headers, tenant_id="t9")
    captured = client.post("/consents/capture", json={
        "tenant_id": "t9", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [
            {"data_category": "PAN", "purpose": "KYC"},
            {"data_category": "Contact Details", "purpose": "Marketing"},
        ],
    }).json()
    kyc_id = next(r["id"] for r in captured if r["data_category"] == "PAN")
    marketing_id = next(r["id"] for r in captured if r["data_category"] == "Contact Details")

    client.post(f"/consents/{marketing_id}/withdraw", json={"actor": "dp1"})

    vault = client.get("/consents", params={"tenant_id": "t9", "data_principal_id": "dp1"}).json()
    kyc_row = next(r for r in vault if r["id"] == kyc_id)
    marketing_row = next(r for r in vault if r["id"] == marketing_id)
    assert kyc_row["withdrawn_at"] is None
    assert marketing_row["withdrawn_at"] is not None


def test_audit_trail_records_capture_and_withdrawal(client, auth_headers):
    notice_id = _approve_new_notice(client, auth_headers, tenant_id="t10")
    consent_id = client.post("/consents/capture", json={
        "tenant_id": "t10", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    }).json()[0]["id"]

    client.post(f"/consents/{consent_id}/withdraw", json={"actor": "dp1", "reason": "no longer needed"})

    audit = client.get(f"/consents/{consent_id}/audit").json()
    event_types = [e["event_type"] for e in audit]
    assert event_types == ["captured", "withdrawn"]
    assert audit[1]["detail"] == "no longer needed"


def test_modify_changes_duration_and_returns_the_updated_record(client, auth_headers):
    notice_id = _approve_new_notice(client, auth_headers, tenant_id="t11")
    consent_id = client.post("/consents/capture", json={
        "tenant_id": "t11", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC", "duration_days": 365}],
    }).json()[0]["id"]

    modified = client.patch(f"/consents/{consent_id}", json={
        "duration_days": 90, "actor": "dp1", "reason": "shortened at my request",
    })
    assert modified.status_code == 200, modified.text
    assert modified.json()["duration_days"] == 90
    assert modified.json()["withdrawn_at"] is None


def test_modify_can_clear_duration_to_null(client, auth_headers):
    notice_id = _approve_new_notice(client, auth_headers, tenant_id="t12")
    consent_id = client.post("/consents/capture", json={
        "tenant_id": "t12", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC", "duration_days": 30}],
    }).json()[0]["id"]

    modified = client.patch(f"/consents/{consent_id}", json={"duration_days": None, "actor": "dp1"})
    assert modified.status_code == 200
    assert modified.json()["duration_days"] is None


def test_modify_only_touches_duration_never_purpose_or_category(client, auth_headers):
    notice_id = _approve_new_notice(client, auth_headers, tenant_id="t13")
    consent_id = client.post("/consents/capture", json={
        "tenant_id": "t13", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    }).json()[0]["id"]

    modified = client.patch(f"/consents/{consent_id}", json={"duration_days": 180, "actor": "dp1"}).json()
    assert modified["data_category"] == "PAN"
    assert modified["purpose"] == "KYC"


def test_modify_rejects_a_withdrawn_consent(client, auth_headers):
    notice_id = _approve_new_notice(client, auth_headers, tenant_id="t14")
    consent_id = client.post("/consents/capture", json={
        "tenant_id": "t14", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    }).json()[0]["id"]
    client.post(f"/consents/{consent_id}/withdraw", json={"actor": "dp1"})

    modified = client.patch(f"/consents/{consent_id}", json={"duration_days": 30, "actor": "dp1"})
    assert modified.status_code == 409


def test_modify_404_for_unknown_consent(client, auth_headers):
    resp = client.patch("/consents/no-such-id", json={"duration_days": 30, "actor": "dp1"})
    assert resp.status_code == 404


def test_audit_trail_records_modification(client, auth_headers):
    notice_id = _approve_new_notice(client, auth_headers, tenant_id="t15")
    consent_id = client.post("/consents/capture", json={
        "tenant_id": "t15", "data_principal_id": "dp1", "notice_id": notice_id,
        "grants": [{"data_category": "PAN", "purpose": "KYC", "duration_days": 365}],
    }).json()[0]["id"]

    client.patch(f"/consents/{consent_id}", json={"duration_days": 30, "actor": "dp1", "reason": "renewal cycle"})

    audit = client.get(f"/consents/{consent_id}/audit").json()
    event_types = [e["event_type"] for e in audit]
    assert event_types == ["captured", "modified"]
    assert "365" in audit[1]["detail"] and "30" in audit[1]["detail"]
    assert "renewal cycle" in audit[1]["detail"]


def test_notices_are_tenant_scoped(client, auth_headers):
    notice_a = _approve_new_notice(client, auth_headers, tenant_id="tenant-a", content="A's notice")
    # tenant-b has no approved notice at all
    resp = client.post("/consents/capture", json={
        "tenant_id": "tenant-b", "data_principal_id": "dp1", "notice_id": notice_a,
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    })
    assert resp.status_code == 404
