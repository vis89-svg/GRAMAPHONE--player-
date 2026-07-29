from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.dependencies.database import get_db
from api.services.auth_service import (
    create_user, authenticate_user, get_user_by_id, get_profile, update_profile,
    create_access_token, create_refresh_token, decode_token
)
from api.schemas.auth import (
    UserRegister, UserLogin, TokenResponse, RefreshTokenRequest,
    ProfileResponse, ProfileUpdate, OnboardingStep1, OnboardingStep2
)
from api.models import User, Profile
import uuid

router = APIRouter(prefix="/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(401, "Invalid token type")
        user_id = uuid.UUID(payload.get("sub"))
    except Exception:
        raise HTTPException(401, "Invalid token")
    
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(401, "User not found")
    return user


async def get_current_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Profile:
    profile = await get_profile(db, user.id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    return profile


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    data: UserRegister,
    db: AsyncSession = Depends(get_db)
):
    # Check if user exists
    result = await db.execute(
        select(User).where(User.email == data.email)
    )
    if result.scalar_one_or_none():
        raise HTTPException(400, "Email already registered")

    user = await create_user(db, data.email, data.password)
    profile = await get_profile(db, user.id)
    
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    
    await db.commit()
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        profile=ProfileResponse.model_validate(profile)
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    user = await authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    
    profile = await get_profile(db, user.id)
    
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        profile=ProfileResponse.model_validate(profile)
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    try:
        payload = decode_token(data.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(401, "Invalid token type")
        user_id = uuid.UUID(payload.get("sub"))
    except Exception:
        raise HTTPException(401, "Invalid refresh token")
    
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(401, "User not found")
    
    profile = await get_profile(db, user.id)
    
    access_token = create_access_token({"sub": str(user.id)})
    new_refresh_token = create_refresh_token({"sub": str(user.id)})
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        profile=ProfileResponse.model_validate(profile)
    )


@router.get("/me", response_model=ProfileResponse)
async def get_me(profile: Profile = Depends(get_current_profile)):
    return ProfileResponse.model_validate(profile)


@router.put("/me", response_model=ProfileResponse)
async def update_me(
    data: ProfileUpdate,
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    updated = await update_profile(db, profile.user_id, data.model_dump(exclude_unset=True))
    await db.commit()
    return ProfileResponse.model_validate(updated)


@router.post("/onboarding/step1")
async def onboarding_step1(
    data: OnboardingStep1,
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    profile.languages = data.languages
    await db.commit()
    return {"status": "ok", "next": "step2"}


@router.post("/onboarding/step2")
async def onboarding_step2(
    data: OnboardingStep2,
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    profile.fav_artists = data.artists
    await db.commit()
    
    # Trigger initial blueprint generation
    from api.services.blueprint_service import blueprint_service
    await blueprint_service.generate_blueprint(db, profile.id)
    
    return {"status": "completed", "profile": ProfileResponse.model_validate(profile)}