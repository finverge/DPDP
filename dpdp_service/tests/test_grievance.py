"""Grievance + DPO-contact module — FSD Sec. 8.3, BRD P360-11."""


def _create_grievance(client, tenant_id="g1"):
    resp = client.post("/grievances", json={
        "tenant_id": tenant_id, "data_principal_id": "dp1",
        "category": "consent", "subject": "Marketing SMS after withdrawal",
        "description": "I withdrew marketing consent but still got an SMS yesterday.",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_create_and_get_grievance(client, auth_headers):
    created = _create_grievance(client)
    assert created["status"] == "Open"
    fetched = client.get(f"/grievances/{created['id']}", headers=auth_headers("g1"))
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_get_grievance_without_auth_is_401(client):
    created = _create_grievance(client, tenant_id="g1b")
    resp = client.get(f"/grievances/{created['id']}")
    assert resp.status_code == 401


def test_list_grievances_filtered_by_tenant_and_status(client, auth_headers):
    _create_grievance(client, tenant_id="g2")
    _create_grievance(client, tenant_id="g2")
    other_tenant = _create_grievance(client, tenant_id="g3")

    listed = client.get("/grievances", params={"tenant_id": "g2"}, headers=auth_headers("g2")).json()
    assert len(listed) == 2
    assert all(g["tenant_id"] == "g2" for g in listed)
    assert all(g["id"] != other_tenant["id"] for g in listed)

    open_only = client.get("/grievances", params={"tenant_id": "g2", "status": "Open"}, headers=auth_headers("g2")).json()
    assert len(open_only) == 2


def test_resolve_grievance_and_double_resolve_is_409(client, auth_headers):
    created = _create_grievance(client, tenant_id="g4")
    headers = auth_headers("g4", role="compliance_officer")
    resolve = client.post(f"/grievances/{created['id']}/resolve", json={
        "resolved_by": "compliance_officer_1", "resolution_note": "Fixed the marketing suppression list bug.",
    }, headers=headers)
    assert resolve.status_code == 200
    body = resolve.json()
    assert body["status"] == "Resolved"
    assert body["resolved_at"] is not None

    again = client.post(f"/grievances/{created['id']}/resolve", json={
        "resolved_by": "compliance_officer_1", "resolution_note": "duplicate",
    }, headers=headers)
    assert again.status_code == 409


def test_flag_frivolous_sets_status_rejected(client, auth_headers):
    created = _create_grievance(client, tenant_id="g5")
    flagged = client.post(f"/grievances/{created['id']}/flag-frivolous", json={
        "flagged_by": "compliance_officer_1", "note": "Same complaint filed 5 times with no new information.",
    }, headers=auth_headers("g5", role="compliance_officer"))
    assert flagged.status_code == 200
    body = flagged.json()
    assert body["is_frivolous"] is True
    assert body["status"] == "Rejected"


def test_dpo_contact_upsert_and_get(client, auth_headers):
    headers = auth_headers("g6")
    resp = client.put("/dpo-contact", json={
        "tenant_id": "g6", "name": "Asha Verma", "email": "dpo@example-bank.example", "phone": "+91-99999-00000",
    }, headers=headers)
    assert resp.status_code == 200
    fetched = client.get("/dpo-contact", params={"tenant_id": "g6"})
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Asha Verma"

    # upsert overwrites, does not duplicate
    client.put("/dpo-contact", json={"tenant_id": "g6", "name": "New DPO", "email": "newdpo@example-bank.example"}, headers=headers)
    fetched2 = client.get("/dpo-contact", params={"tenant_id": "g6"}).json()
    assert fetched2["name"] == "New DPO"


def test_dpo_contact_put_without_auth_is_401(client):
    resp = client.put("/dpo-contact", json={"tenant_id": "g6b", "name": "X", "email": "x@x.com"})
    assert resp.status_code == 401


def test_dpo_contact_404_when_not_published(client):
    resp = client.get("/dpo-contact", params={"tenant_id": "no-such-tenant"})
    assert resp.status_code == 404
