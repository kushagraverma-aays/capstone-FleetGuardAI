"""Password hashing and JWT issuing.

Enforcement is wired up in the auth dependency, not here; this module only
knows how to hash, verify, and sign. AUTH_ENABLED decides whether any of it is
consulted at request time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.config import settings

# bcrypt is called directly rather than through passlib. passlib 1.7.4 reads
# bcrypt.__about__.__version__ at import time to detect the backend, and that
# attribute was removed in bcrypt 4.1, so the pair either warns loudly or
# refuses to hash depending on the versions that resolve on the host. The
# direct API is three lines and has no such coupling.

# bcrypt hashes at most 72 bytes and raises on anything longer, so the input is
# truncated on the way in. Both hashing and verification truncate identically,
# which is what keeps a long password verifiable against its own hash.
_BCRYPT_MAX_BYTES = 72


def _prepare(plain: str) -> bytes:
    return plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_prepare(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    # A stored hash can be malformed - truncated by an old migration, or
    # written by a different scheme - and checkpw raises rather than returning
    # False for those. A bad hash is a failed login, not a 500.
    try:
        return bcrypt.checkpw(_prepare(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, claims: dict[str, Any] | None = None) -> str:
    expires = datetime.now(UTC) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload: dict[str, Any] = {"sub": subject, "exp": expires, "iat": datetime.now(UTC)}
    if claims:
        payload.update(claims)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError subclasses on an invalid or expired token."""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
