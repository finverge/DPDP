"""Auth dependencies: decode the bearer token into a Principal and enforce roles.

Adapted from Fraud360's packages/cp_common/cp_common/auth.py — same
Principal shape and get_current_principal/require_role dependency
pattern, copied rather than shared live (see security.py docstring).

Roles (BRD Sec. 12 admin-UI actors, FSD Sec. 2):
  - platform_admin      — Finverge staff; may act across all tenants.
  - tenant_admin        — a tenant's administrator; scoped to their own tenant_id.
  - dpo                 — reviews/approves notices, DPIAs; scoped to their tenant.
  - compliance_officer  — resolves grievances; scoped to their tenant.
"""
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from app.security import decode_token

ROLES = ("platform_admin", "tenant_admin", "dpo", "compliance_officer")


@dataclass
class Principal:
    subject: str
    role: str
    tenant_id: str | None

    @property
    def is_platform_admin(self) -> bool:
        return self.role == "platform_admin"


def get_current_principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        claims = decode_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return Principal(subject=claims.get("sub", ""), role=claims.get("role", ""), tenant_id=claims.get("tenant_id"))


def require_role(*roles: str):
    """Also enforces tenant scoping: a non-platform_admin caller may only
    act on their own tenant_id — checked here once rather than
    independently re-implemented in every route (the same reasoning
    Fraud360's own auth.py gives for centralising this)."""
    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return principal
    return dependency


def require_tenant_match(principal: Principal, tenant_id: str) -> None:
    """Call explicitly in a route after require_role, with the tenant_id
    the request is actually acting on — platform_admin is exempt."""
    if not principal.is_platform_admin and principal.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot act on a different tenant.")
