"""
Authentication endpoints.

Not explicitly detailed in the PRD beyond "implement basic API
authentication, preferably JWT," so this module adds the minimal
register/login pair needed to obtain a token for the RBAC-protected
endpoints elsewhere in the API. A full OAuth flow is explicitly out of
scope (PRD section 16).
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from src.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> UserResponse:
    """Create a user account with a given role (ADMIN or CLIENT). In a real
    deployment, granting ADMIN would itself be an admin-only action; it is
    left open here for local evaluation/testing convenience."""
    user = auth_service.register(db, payload)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Exchange email/password for a JWT access token."""
    return auth_service.login(db, payload)
