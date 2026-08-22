"""Password hashing and JWT issuance.

argon2 directly rather than via passlib: passlib has been effectively unmaintained
since 2020 and its bcrypt backend detection breaks on modern bcrypt releases.
argon2-cffi is the reference implementation and needs no wrapper.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import get_settings

# Use a 32 MiB Argon2id working set with one lane. The previous 64 MiB policy
# still failed late in long Windows integration runs: native Argon2 allocations
# were eventually refused even though each individual hash normally succeeded.
# This keeps Argon2id, its time cost, and per-password salts intact while fitting
# the API process alongside the Docker-backed test clients and local services.
_hasher = PasswordHasher(memory_cost=32 * 1024, parallelism=1)


# @spec ACCESS-AUTH-001
def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time verify. Returns False rather than raising on a bad hash."""
    try:
        _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return True


def needs_rehash(hashed: str) -> bool:
    """True when the stored hash used weaker parameters than the current policy."""
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True


def create_opaque_token() -> str:
    """Create a high-entropy token that is safe to place in a one-time link."""
    return secrets.token_urlsafe(32)


# @spec ACCESS-AUTH-006
def hash_opaque_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# @spec ACCESS-AUTH-002
def create_access_token(user_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# @spec ACCESS-AUTH-004
def decode_access_token(token: str) -> uuid.UUID | None:
    """Return the subject, or None if the token is invalid, expired, or malformed."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None

    subject = payload.get("sub")
    if not subject:
        return None

    try:
        return uuid.UUID(subject)
    except ValueError:
        return None
