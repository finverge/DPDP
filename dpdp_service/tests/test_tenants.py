"""Phase 2 — multi-tenant onboarding, white-label branding, usage metering."""


def test_create_tenant_gets_a_unique_api_key(client):
    t1 = client.post("/tenants", json={"name": "Acme Fintech", "plan": "trial"}).json()
    t2 = client.post("/tenants", json={"name": "Beta Bank", "plan": "saas"}).json()
    assert t1["api_key"] != t2["api_key"]
    assert t1["api_key"].startswith("cb_live_")
    assert t1["plan"] == "trial"
    assert t2["plan"] == "saas"


def test_get_tenant_404_when_missing(client):
    resp = client.get("/tenants/no-such-tenant")
    assert resp.status_code == 404


def test_get_tenant_never_returns_the_plaintext_key(client):
    created = client.post("/tenants", json={"name": "NoLeak Bank"}).json()
    fetched = client.get(f"/tenants/{created['id']}").json()
    assert "api_key" not in fetched
    assert fetched["api_key_prefix"] == created["api_key"][:16]


def test_rotate_api_key_issues_a_new_key_and_keeps_old_one_in_grace(client, auth_headers):
    created = client.post("/tenants", json={"name": "Rotate Bank"}).json()
    tid = created["id"]
    headers = auth_headers(tid)

    rotated = client.post(f"/tenants/{tid}/rotate-api-key", headers=headers)
    assert rotated.status_code == 200, rotated.text
    body = rotated.json()
    assert body["api_key"] != created["api_key"]
    assert body["api_key_prefix"] == body["api_key"][:16]

    fetched = client.get(f"/tenants/{tid}").json()
    assert fetched["previous_api_key_expires_at"] is not None


def test_rotate_api_key_requires_auth(client):
    created = client.post("/tenants", json={"name": "NoAuth Bank"}).json()
    resp = client.post(f"/tenants/{created['id']}/rotate-api-key")
    assert resp.status_code == 401


def test_verify_api_key_accepts_current_and_grace_period_old_key(client, auth_headers):
    from app.db import SessionLocal
    from app.models import Tenant
    from app.tenant_keys import verify_api_key

    created = client.post("/tenants", json={"name": "Verify Bank"}).json()
    tid = created["id"]
    old_plain = created["api_key"]
    headers = auth_headers(tid)

    rotated = client.post(f"/tenants/{tid}/rotate-api-key", headers=headers).json()
    new_plain = rotated["api_key"]

    db = SessionLocal()
    try:
        tenant = db.get(Tenant, tid)
        assert verify_api_key(tenant, new_plain) is True
        assert verify_api_key(tenant, old_plain) is True  # still valid — grace period
        assert verify_api_key(tenant, "not-a-real-key") is False
    finally:
        db.close()


def test_process_due_rotations_only_rotates_whats_actually_due(client, auth_headers):
    from datetime import datetime, timedelta, timezone
    from app.db import SessionLocal
    from app.models import Tenant
    from app.tenant_keys import process_due_rotations

    created = client.post("/tenants", json={"name": "DueSoon Bank"}).json()
    tid = created["id"]

    db = SessionLocal()
    try:
        tenant = db.get(Tenant, tid)
        original_hash = tenant.api_key_hash
        tenant.api_key_rotate_by = datetime.now(timezone.utc) - timedelta(seconds=1)  # force it due
        db.commit()

        processed = process_due_rotations(db)
        assert processed == 1
        db.refresh(tenant)
        assert tenant.api_key_hash != original_hash
        assert tenant.previous_api_key_hash == original_hash

        # a second run finds nothing due (rotate_by was just reset into the future)
        assert process_due_rotations(db) == 0
    finally:
        db.close()


def test_rotate_due_api_keys_endpoint_requires_platform_admin(client, auth_headers):
    created = client.post("/tenants", json={"name": "MaintEndpoint Bank"}).json()
    resp = client.post("/tenants/rotate-due-api-keys", headers=auth_headers(created["id"]))
    assert resp.status_code == 403

    resp2 = client.post("/tenants/rotate-due-api-keys", headers=auth_headers(None, role="platform_admin"))
    assert resp2.status_code == 200
    assert "rotated" in resp2.json()


def test_update_branding_is_partial(client, auth_headers):
    created = client.post("/tenants", json={"name": "Acme"}).json()
    tid = created["id"]
    headers = auth_headers(tid)

    r1 = client.put(f"/tenants/{tid}/branding", json={"brand_primary_color": "#17A673"}, headers=headers)
    assert r1.status_code == 200
    assert r1.json()["brand_primary_color"] == "#17A673"
    assert r1.json()["brand_logo_url"] is None

    r2 = client.put(f"/tenants/{tid}/branding", json={"brand_logo_url": "https://acme.example/logo.png"}, headers=headers)
    body = r2.json()
    # first field untouched by the second, partial update
    assert body["brand_primary_color"] == "#17A673"
    assert body["brand_logo_url"] == "https://acme.example/logo.png"


def test_update_branding_without_auth_is_401(client):
    created = client.post("/tenants", json={"name": "Acme2"}).json()
    resp = client.put(f"/tenants/{created['id']}/branding", json={"brand_primary_color": "#000000"})
    assert resp.status_code == 401


def test_usage_counts_reflect_real_activity(client, auth_headers):
    created = client.post("/tenants", json={"name": "UsageCo"}).json()
    tid = created["id"]
    headers = auth_headers(tid)

    # notices/consent capture generates a real consent.capture usage event
    draft = client.post("/notices", json={"tenant_id": tid, "language": "English", "content": "notice"}, headers=headers).json()
    client.post(f"/notices/{draft['id']}/approve", json={"approved_by": "dpo"}, headers=headers)
    client.post("/consents/capture", json={
        "tenant_id": tid, "data_principal_id": "dp1", "notice_id": draft["id"],
        "grants": [{"data_category": "PAN", "purpose": "KYC"}],
    })
    client.post("/grievances", json={
        "tenant_id": tid, "data_principal_id": "dp1", "category": "consent", "subject": "x", "description": "y",
    })

    usage = client.get(f"/tenants/{tid}/usage", headers=headers).json()
    assert usage["counts"].get("consent.capture") == 1
    assert usage["counts"].get("grievance.create") == 1


def test_usage_is_tenant_scoped(client, auth_headers):
    t1 = client.post("/tenants", json={"name": "T1"}).json()
    t2 = client.post("/tenants", json={"name": "T2"}).json()
    client.post("/grievances", json={
        "tenant_id": t1["id"], "data_principal_id": "dp1", "category": "c", "subject": "s", "description": "d",
    })
    usage_t2 = client.get(f"/tenants/{t2['id']}/usage", headers=auth_headers(t2["id"])).json()
    assert usage_t2["counts"].get("grievance.create", 0) == 0


def test_usage_across_tenants_is_forbidden_cross_tenant(client, auth_headers):
    """A tenant_admin for t1 cannot read t2's usage, even by guessing the id."""
    t1 = client.post("/tenants", json={"name": "T1x"}).json()
    t2 = client.post("/tenants", json={"name": "T2x"}).json()
    resp = client.get(f"/tenants/{t2['id']}/usage", headers=auth_headers(t1["id"]))
    assert resp.status_code == 403
