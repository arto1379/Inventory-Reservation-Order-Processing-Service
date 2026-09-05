"""Business logic for registration/login (PRD section 16)."""
from sqlalchemy.orm import Session

from src.core.exceptions import InvalidRequestError, UnauthorizedError
from src.core.ids import generate_id
from src.core.security import create_access_token, hash_password, verify_password
from src.models.user import User
from src.repositories import user_repository
from src.schemas.auth import LoginRequest, RegisterRequest, TokenResponse


def register(db: Session, payload: RegisterRequest) -> User:
    if user_repository.get_by_email(db, payload.email) is not None:
        raise InvalidRequestError("A user with this email already exists", {"email": payload.email})

    user = User(id=generate_id("user"), email=payload.email, hashed_password=hash_password(payload.password), role=payload.role)
    user_repository.create(db, user)
    db.commit()
    db.refresh(user)
    return user


def login(db: Session, payload: LoginRequest) -> TokenResponse:
    user = user_repository.get_by_email(db, payload.email)
    if user is None or not verify_password(payload.password, user.hashed_password):
        # Deliberately identical error for "no such user" and "wrong
        # password" so the API never leaks which emails are registered.
        raise UnauthorizedError("Invalid email or password")

    token = create_access_token(subject=user.id, email=user.email, role=user.role.value)
    return TokenResponse(access_token=token, role=user.role)
