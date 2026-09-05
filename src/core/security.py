"""
Password hashing and JWT issuance/verification.

Auth design (see README > "How API authentication is structured"):

  - Passwords are hashed with bcrypt (via passlib) and never stored or
    logged in plaintext.
  - Access is a stateless JWT containing the user id, email, and role.
    Roles are ADMIN and CLIENT (see src/models/user.py::UserRole).
  - A full OAuth flow is explicitly out of scope per the PRD; this is a
    deliberately small, self-contained login/JWT scheme.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from src.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password for storage."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plaintext password against a stored bcrypt hash."""
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(*, subject: str, email: str, role: str) -> str:
    """
    Issue a signed JWT for an authenticated user.

    `subject` is the user's ID (stored in the standard "sub" claim); email
    and role are embedded so downstream request handling never needs a
    database round-trip just to authorize a request.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": subject,
        "email": email,
        "role": role,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT, returning its claims.

    Raises `jose.JWTError` on any invalid/expired/tampered token; callers
    (see src/api/deps.py) are responsible for translating that into an
    UnauthorizedError.
    """
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


__all__ = ["hash_password", "verify_password", "create_access_token", "decode_access_token", "JWTError"]
