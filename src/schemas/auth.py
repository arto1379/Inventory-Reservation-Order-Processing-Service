"""Request/response schemas for the authentication endpoints."""
from pydantic import BaseModel, EmailStr, Field

from src.models.enums import UserRole


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.CLIENT


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    role: UserRole

    model_config = {"from_attributes": True}
