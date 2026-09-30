"""Test fixtures. Each test session gets a fresh, disposable SQLite file so
tests never touch whatever DATABASE_URL a developer has set locally — that
variable is deliberately overridden here, not read. Pattern mirrors the
sibling AML360 service's own conftest.py for the same reason: a Windows
SQLite file lock survives until every connection against it is closed, so
disposal must happen before deletion, and a leftover file must not fail the
suite (the next run deletes it before use)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TEST_DB = ROOT / "tests" / "_test.db"
os.environ["DPDP_DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["DPDP_INTERNAL_API_KEY"] = "test-internal-key"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _fresh_database():
    if _TEST_DB.exists():
        _TEST_DB.unlink()
    import app.models  # noqa: F401 — registers every table on Base.metadata before create_all
    from app.db import engine, init_db
    init_db()
    yield
    engine.dispose()
    try:
        if _TEST_DB.exists():
            _TEST_DB.unlink()
    except OSError:
        pass


@pytest.fixture()
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture()
def auth_headers(client):
    """Factory fixture: auth_headers(tenant_id, role="tenant_admin", email=None)
    registers a fresh user (a new email each call, so re-registration never
    409s) and returns a ready-to-use {"Authorization": "Bearer ..."} dict —
    the one helper every test touching a now-protected admin endpoint needs,
    instead of each test hand-rolling register+login."""
    import itertools
    counter = itertools.count()

    def _make(tenant_id: str | None, role: str = "tenant_admin", email: str | None = None):
        email = email or f"test-user-{next(counter)}@example.com"
        headers = {"X-Internal-Key": "test-internal-key"} if role == "platform_admin" else {}
        client.post("/auth/register", json={
            "tenant_id": tenant_id, "email": email, "password": "test-password-123", "role": role,
        }, headers=headers)
        token = client.post("/auth/login", json={
            "tenant_id": tenant_id, "email": email, "password": "test-password-123",
        }).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _make
