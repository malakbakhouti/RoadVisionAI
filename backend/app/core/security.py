"""Security primitives — Argon2id password hashing + JWT (SD01, APISpec §3).

Design notes
------------
* Argon2id via `argon2-cffi` directly. Micro-ADR vs TechStack's "passlib[argon2]":
  passlib is unmaintained and relies on the stdlib `crypt` module removed in
  Python 3.13; argon2-cffi IS the underlying implementation passlib would call.
  Same algorithm, same hashes, one less broken dependency.
* JWT is stateless: schema v4.2 has no token table and must not be modified,
  so revocation-on-logout is client-side (discard) + audit trail; the 30-min
  access TTL bounds the exposure window. Server-side revocation is a documented
  evolution pathway (would require a new table -> ADR).
* Tokens carry `type` ("access" | "refresh") and are never interchangeable.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from app.core.config import Settings

_hasher = PasswordHasher()  # argon2id, OWASP-recommended defaults

TokenType = Literal["access", "refresh"]


# --- Passwords ---------------------------------------------------------------
def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, plain)
    except (VerifyMismatchError, VerificationError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# --- JWT ---------------------------------------------------------------------
class TokenError(Exception):
    """Raised when a token is invalid, expired, or of the wrong type."""


def _create_token(
    *,
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    settings: Settings,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
        **(extra_claims or {}),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, role: str, settings: Settings) -> str:
    return _create_token(
        subject=str(user_id),
        token_type="access",
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        settings=settings,
        extra_claims={"role": role},
    )


def create_refresh_token(user_id: uuid.UUID, settings: Settings) -> str:
    return _create_token(
        subject=str(user_id),
        token_type="refresh",
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
        settings=settings,
    )


def decode_token(token: str, expected_type: TokenType, settings: Settings) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid token") from exc
    if payload.get("type") != expected_type:
        raise TokenError(f"Expected {expected_type} token")
    return payload
