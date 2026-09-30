"""Password hashing and JWT issue/verify.

Adapted from Fraud360's packages/cp_common/cp_common/security.py — same
bcrypt + PyJWT primitives, same token shape (sub/role/tenant_id/scope +
iat/exp) — but copied into dpdp_service rather than imported live, since
ConsentBridge must run standalone for a third-party tenant who has no
Fraud360 control-plane at all (see BRD Sec. 12/roadmap "internal dogfood
vs. external SaaS" split). Dropped from the original: SSO, MFA, refresh
tokens, session listing, machine credentials — a real v1 scope decision
(FSD "not yet built" list), not an oversight.
"""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

# Dev-only default — MUST be overridden via DPDP_JWT_SECRET in any shared
# environment. Not validated at startup (unlike Fraud360's fail-fast
# pattern for ISO8583_FAIL_OPEN) because that would break every existing
# test/dev workflow that predates this module; tracked as a hardening
# follow-up, same honesty standard as everything else "not yet built" here.
JWT_SECRET = os.environ.get("DPDP_JWT_SECRET", "dev-only-insecure-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("DPDP_JWT_EXPIRE_MINUTES", "480"))

# Gates POST /auth/register for role=platform_admin only (routes_auth.py) — same
# X-Internal-Key precedent as Fraud360's cp_common.auth.require_internal_key,
# copied rather than made a shared dependency for the same standalone-service
# reason this whole module gives. Same dev-only-default caveat as JWT_SECRET
# above: MUST be overridden via DPDP_INTERNAL_API_KEY in any shared environment.
INTERNAL_API_KEY = os.environ.get("DPDP_INTERNAL_API_KEY", "dev-only-insecure-internal-key-change-me")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(*, subject: str, role: str, tenant_id: str | None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "tenant_id": tenant_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=JWT_EXPIRE_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
