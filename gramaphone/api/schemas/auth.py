from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
import uuid


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    profile: "ProfileResponse"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class ProfileResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    languages: list[str]
    fav_artists: list[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    languages: Optional[list[str]] = None
    fav_artists: Optional[list[str]] = None


class OnboardingStep1(BaseModel):
    languages: list[str] = Field(..., min_length=1)


class OnboardingStep2(BaseModel):
    artists: list[str] = Field(..., min_length=3)