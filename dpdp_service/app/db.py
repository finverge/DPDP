"""Database engine, session factory, and a FastAPI session dependency.

Standalone by design (see package docstring): this service owns its own
data, no shared schema or connection with DLP LOS or Fraud360.

Defaults to the local Postgres instance already running on this dev
machine (postgres/postgres @ localhost:5432, database
dpdp_consent_platform — created once via `CREATE DATABASE`, not managed
by this file) rather than the SQLite file this service started on. The
ORM usage here is plain enough to work unchanged against either — set
DPDP_DATABASE_URL to point anywhere else (a shared dev Postgres, a
managed instance, or back to `sqlite:///...` for a zero-setup laptop
run) without code changes, same convention as the sibling AML360
service. Tests never depend on this default — conftest.py always sets
DPDP_DATABASE_URL to its own disposable SQLite file before this module
is imported, so switching this default never touches the test suite.
"""
import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_DEFAULT_POSTGRES_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/dpdp_consent_platform"
DATABASE_URL = os.environ.get("DPDP_DATABASE_URL", _DEFAULT_POSTGRES_URL)


class Base(DeclarativeBase):
    """Declarative base for every DPDP Consent Platform model."""


_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Create every table. Dev/test convenience — swap for a real migration
    tool (Alembic) before production, same as the AML360 sibling service."""
    Base.metadata.create_all(bind=engine)
