"""Admin login — register/login/me. Pattern copied from Fraud360's
tenant_service/app/routes/auth.py (see security.py, auth.py docstrings):
generic "invalid email or password" for both an unknown address and a
wrong password (so a failed attempt never reveals which one), and a
simple failed-attempt lockout. MFA, refresh tokens, SSO, and session
listing are Fraud360 features deliberately not copied — a v1 scope
decision, not an oversight (see FSD "not yet built").
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Principal, ROLES, get_current_principal
from app.db import get_session
from app.models import User
from app.schemas import UserRegisterIn, UserOut, LoginIn, TokenOut
from app.security import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

_LOCKOUT_THRESHOLD = 5
_LOCKOUT_MINUTES = 15


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite doesn't reliably round-trip tzinfo through DateTime(timezone=True)
    — a value read back can come out naive even though it was stored aware
    (the same class of bug AML360's own test suite exists to catch, per its
    conftest.py comment). Normalize to UTC-aware before ever comparing."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@router.post("/register", response_model=UserOut)
def register(req: UserRegisterIn, db: Session = Depends(get_session)):
    """No auth guard on this endpoint by design for v1 — the very first
    tenant_admin for a brand-new tenant has no token yet to present.
    Real deployments will want this gated behind an invite flow or an
    internal key (Fraud360's require_internal_key is the precedent);
    tracked as a hardening follow-up, not hidden."""
    if req.role not in ROLES:
        raise HTTPException(status_code=422, detail=f"Unknown role '{req.role}' — expected one of {ROLES}.")
    if req.role != "platform_admin" and not req.tenant_id:
        raise HTTPException(status_code=422, detail="tenant_id is required for every role except platform_admin.")

    existing = db.execute(
        select(User).where(User.tenant_id == req.tenant_id, User.email == req.email)
    ).scalars().first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="A user with this email already exists for this tenant.")

    user = User(tenant_id=req.tenant_id, email=req.email, password_hash=hash_password(req.password), role=req.role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenOut)
def login(req: LoginIn, db: Session = Depends(get_session)):
    user = db.execute(
        select(User).where(User.tenant_id == req.tenant_id, User.email == req.email)
    ).scalars().first()

    # Same generic error whether the address is unknown or the password
    # is wrong — distinguishing them tells an attacker which addresses
    # are worth attacking (Fraud360's own auth.py login docstring).
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    locked_until = _aware(user.locked_until)
    if locked_until and locked_until > _utcnow():
        remaining = int((locked_until - _utcnow()).total_seconds() // 60) + 1
        raise HTTPException(status_code=423, detail=f"Too many failed attempts. Try again in {remaining} minute(s).")

    if not verify_password(req.password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= _LOCKOUT_THRESHOLD:
            user.locked_until = _utcnow() + timedelta(minutes=_LOCKOUT_MINUTES)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    user.failed_attempts = 0
    user.locked_until = None
    db.commit()

    token = create_access_token(subject=user.email, role=user.role, tenant_id=user.tenant_id)
    return TokenOut(access_token=token, role=user.role, tenant_id=user.tenant_id)


@router.get("/me", response_model=UserOut)
def whoami(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_session)):
    user = db.execute(
        select(User).where(User.tenant_id == principal.tenant_id, User.email == principal.subject)
    ).scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="Token is valid but no matching user record exists.")
    return user
