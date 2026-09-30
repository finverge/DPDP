"""Admin login — app/auth.py, app/security.py, app/routes_auth.py."""


def _register(client, tenant_id="t1", email="dpo@example.com", password="correct-horse-1", role="tenant_admin"):
    resp = client.post("/auth/register", json={"tenant_id": tenant_id, "email": email, "password": password, "role": role})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_register_and_login_round_trip(client):
    _register(client, tenant_id="auth1")
    resp = client.post("/auth/login", json={"tenant_id": "auth1", "email": "dpo@example.com", "password": "correct-horse-1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "tenant_admin"
    assert body["tenant_id"] == "auth1"
    assert body["access_token"]


def test_login_wrong_password_and_unknown_email_get_the_same_generic_error(client):
    _register(client, tenant_id="auth2", email="a@x.com")
    wrong_pw = client.post("/auth/login", json={"tenant_id": "auth2", "email": "a@x.com", "password": "not-it"})
    unknown = client.post("/auth/login", json={"tenant_id": "auth2", "email": "nobody@x.com", "password": "not-it"})
    assert wrong_pw.status_code == 401
    assert unknown.status_code == 401
    assert wrong_pw.json()["detail"] == unknown.json()["detail"]


def test_register_rejects_unknown_role(client):
    resp = client.post("/auth/register", json={"tenant_id": "auth3", "email": "x@x.com", "password": "password123", "role": "superuser"})
    assert resp.status_code == 422


def test_register_duplicate_email_same_tenant_is_409(client):
    _register(client, tenant_id="auth4", email="dup@x.com")
    again = client.post("/auth/register", json={"tenant_id": "auth4", "email": "dup@x.com", "password": "password123", "role": "dpo"})
    assert again.status_code == 409


def test_same_email_different_tenants_is_allowed(client):
    _register(client, tenant_id="auth5a", email="shared@x.com")
    resp = client.post("/auth/register", json={"tenant_id": "auth5b", "email": "shared@x.com", "password": "password123", "role": "dpo"})
    assert resp.status_code == 200


def test_account_locks_after_repeated_failures(client):
    _register(client, tenant_id="auth6", email="lock@x.com", password="right-password-1")
    for _ in range(5):
        client.post("/auth/login", json={"tenant_id": "auth6", "email": "lock@x.com", "password": "wrong"})
    locked = client.post("/auth/login", json={"tenant_id": "auth6", "email": "lock@x.com", "password": "right-password-1"})
    assert locked.status_code == 423


def test_me_returns_the_authenticated_user(client):
    _register(client, tenant_id="auth7", email="me@x.com", password="password123", role="compliance_officer")
    token = client.post("/auth/login", json={"tenant_id": "auth7", "email": "me@x.com", "password": "password123"}).json()["access_token"]
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@x.com"
    assert resp.json()["role"] == "compliance_officer"


def test_me_without_token_is_401(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_platform_admin_has_no_tenant_id(client):
    resp = client.post(
        "/auth/register", json={"email": "platform@finverge.example", "password": "password123", "role": "platform_admin"},
        headers={"X-Internal-Key": "test-internal-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] is None


def test_platform_admin_registration_without_internal_key_is_401(client):
    resp = client.post("/auth/register", json={"email": "no-key@finverge.example", "password": "password123", "role": "platform_admin"})
    assert resp.status_code == 401


def test_platform_admin_registration_with_wrong_internal_key_is_401(client):
    resp = client.post(
        "/auth/register", json={"email": "wrong-key@finverge.example", "password": "password123", "role": "platform_admin"},
        headers={"X-Internal-Key": "not-the-real-key"},
    )
    assert resp.status_code == 401


def test_tenant_scoped_roles_never_need_an_internal_key(client):
    """The gate is specific to platform_admin — every other role must keep
    registering exactly as before, with no header at all, since that's the
    self-service tenant-bootstrap path this endpoint has to stay open for."""
    for role in ("tenant_admin", "dpo", "compliance_officer"):
        resp = client.post("/auth/register", json={
            "tenant_id": f"no-key-needed-{role}", "email": f"{role}@x.com", "password": "password123", "role": role,
        })
        assert resp.status_code == 200, (role, resp.text)


def test_non_platform_admin_requires_tenant_id(client):
    resp = client.post("/auth/register", json={"email": "x@x.com", "password": "password123", "role": "tenant_admin"})
    assert resp.status_code == 422
