"""Data Minimization & Masking — FSD Sec. 4, BRD P360-04/05."""


def test_apply_without_policy_is_422_and_logged_as_blocked(client, auth_headers):
    resp = client.post("/masking/apply", json={
        "tenant_id": "m1", "purpose": "csv_export", "actor": "analyst_1",
        "records": [{"account_number": "1234567890", "name": "Jane Doe"}],
    })
    assert resp.status_code == 422


def test_upsert_policy_then_apply_masks_and_omits_by_default(client, auth_headers):
    put = client.put("/masking/policies", json={
        "tenant_id": "m2", "purpose": "csv_export", "created_by": "tenant_admin_1",
        "field_rules": {"account_number": "mask_last4", "name": "allow", "ssn": "redact"},
    }, headers=auth_headers("m2"))
    assert put.status_code == 200, put.text

    resp = client.post("/masking/apply", json={
        "tenant_id": "m2", "purpose": "csv_export", "actor": "analyst_1",
        "records": [{"account_number": "1234567890", "name": "Jane Doe", "ssn": "999-99-9999", "internal_notes": "flagged"}],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    record = body["records"][0]
    assert record["account_number"] == "••••••7890"
    assert record["name"] == "Jane Doe"
    assert record["ssn"] == "***REDACTED***"
    # not in field_rules -> omitted by default, not passed through unmasked
    assert "internal_notes" not in record


def test_policy_upsert_is_keyed_on_tenant_and_purpose_not_duplicated(client, auth_headers):
    client.put("/masking/policies", json={
        "tenant_id": "m3", "purpose": "csv_export", "created_by": "a",
        "field_rules": {"x": "allow"},
    }, headers=auth_headers("m3"))
    client.put("/masking/policies", json={
        "tenant_id": "m3", "purpose": "csv_export", "created_by": "b",
        "field_rules": {"x": "redact"},
    }, headers=auth_headers("m3"))
    policies = client.get("/masking/policies", params={"tenant_id": "m3"}).json()
    assert len(policies) == 1
    assert policies[0]["field_rules"]["x"] == "redact"
    assert policies[0]["created_by"] == "b"


def test_apply_rejects_unknown_strategy(client, auth_headers):
    resp = client.put("/masking/policies", json={
        "tenant_id": "m4", "purpose": "csv_export", "created_by": "a",
        "field_rules": {"x": "not_a_real_strategy"},
    }, headers=auth_headers("m4"))
    assert resp.status_code == 422


def test_policies_are_tenant_scoped(client, auth_headers):
    client.put("/masking/policies", json={
        "tenant_id": "m5a", "purpose": "csv_export", "created_by": "a", "field_rules": {"x": "allow"},
    }, headers=auth_headers("m5a"))
    resp = client.post("/masking/apply", json={
        "tenant_id": "m5b", "purpose": "csv_export", "actor": "analyst_1",
        "records": [{"x": "value"}],
    })
    assert resp.status_code == 422  # m5b has no policy of its own


def test_mask_account_device_ip_match_fraud360_local_masking_exactly(client, auth_headers):
    """Parity test against Fraud360's own analytics_service/app/privacy.py
    algorithm (_mask_tail prefix2/tail4 for accounts, prefix1/tail3 for
    device_id, first-two-octets for IPs) — the whole point of these three
    strategies is a byte-identical drop-in, not just an equivalent one."""
    client.put("/masking/policies", json={
        "tenant_id": "parity", "purpose": "fraud360_analytics_export", "created_by": "a",
        "field_rules": {"debtor_account": "mask_account", "device_id": "mask_device", "ip_addr": "mask_ip"},
    }, headers=auth_headers("parity"))
    resp = client.post("/masking/apply", json={
        "tenant_id": "parity", "purpose": "fraud360_analytics_export", "actor": "a",
        "records": [{"debtor_account": "1234567890123", "device_id": "abcdef1234", "ip_addr": "203.0.113.45"}],
    })
    record = resp.json()["records"][0]
    # Fraud360's _mask_tail("1234567890123", keep_prefix=2, keep_tail=4) -> "12" + 7*"•" + "0123"
    assert record["debtor_account"] == "12" + "•" * 7 + "0123"
    # _mask_tail("abcdef1234", keep_prefix=1, keep_tail=3) -> "a" + 6*"•" + "234"
    assert record["device_id"] == "a" + "•" * 6 + "234"
    # _mask_ip("203.0.113.45") -> "203.0.•.•"
    assert record["ip_addr"] == "203.0.•.•"


def test_multiple_records_masked_together(client, auth_headers):
    client.put("/masking/policies", json={
        "tenant_id": "m6", "purpose": "csv_export", "created_by": "a",
        "field_rules": {"account_number": "mask_last4"},
    }, headers=auth_headers("m6"))
    resp = client.post("/masking/apply", json={
        "tenant_id": "m6", "purpose": "csv_export", "actor": "analyst_1",
        "records": [{"account_number": "1111222233"}, {"account_number": "4444555566"}],
    })
    body = resp.json()
    assert len(body["records"]) == 2
    assert body["records"][0]["account_number"].endswith("2233")
    assert body["records"][1]["account_number"].endswith("5566")
