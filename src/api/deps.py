"""
Shared FastAPI dependencies: DB session injection and JWT-based auth/RBAC.

Auth scheme: HTTP Bearer (`Authorization: Bearer <token>`). Obtain a token
via `POST /api/v1/auth/login`, then use the Swagger UI "Authorize" button
(or an `Authorization` header) to call protected endpoints -- see the
generated docs at `/docs`.
"""
from collections.abc import Generator

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.core.exceptions import ForbiddenError, UnauthorizedError
from src.core.security import JWTError, decode_access_token
from src.database import SessionLocal
from src.models.enums import UserRole
from src.models.user import User
from src.repositories import user_repository

_bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Decode the bearer token and load the corresponding user. Raises
    UnauthorizedError (401) for a missing/invalid/expired token or a token
    referencing a user that no longer exists."""
    if credentials is None:
        raise UnauthorizedError("Missing bearer token")
    try:
        claims = decode_access_token(credentials.credentials)
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired token") from exc

    user = user_repository.get_by_id(db, claims.get("sub", ""))
    if user is None:
        raise UnauthorizedError("User no longer exists")
    return user


def require_roles(*allowed_roles: UserRole):
    """
    Dependency factory enforcing RBAC (PRD section 16), e.g.:

        @router.post(..., dependencies=[Depends(require_roles(UserRole.ADMIN))])
    """

    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise ForbiddenError(
                f"Role '{current_user.role.value}' is not permitted to perform this action"
            )
        return current_user

    return _dependency
