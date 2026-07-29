import os
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    APP_ENV: str = "development"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/gramaphone",
        description="PostgreSQL async connection string"
    )

    # Redis (Upstash)
    UPSTASH_REDIS_REST_URL: Optional[str] = Field(
        default=None,
        description="Upstash Redis REST URL"
    )
    UPSTASH_REDIS_REST_TOKEN: Optional[str] = Field(
        default=None,
        description="Upstash Redis REST token"
    )

    # JWT
    JWT_SECRET_KEY: str = Field(
        default="dev-secret-change-in-production",
        description="JWT signing secret"
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # External APIs
    ITUNES_BASE_URL: str = "https://itunes.apple.com"
    DEEZER_BASE_URL: str = "https://api.deezer.com"
    LASTFM_BASE_URL: str = "https://ws.audioscrobbler.com/2.0"
    LASTFM_API_KEY: str = Field(default="", description="Last.fm API key (optional)")

    # YouTube / yt-dlp
    YTDLP_FORMAT: str = "bestaudio"
    YTDLP_TIMEOUT: int = 30

    # Groq API
    GROQ_API_KEY: str = Field(
        default="",
        description="Groq API key for Llama-3.1-8B inference"
    )
    GROQ_MODEL: str = "llama-3.1-8b-instant"
    GROQ_MAX_TOKENS: int = 2048
    GROQ_TEMPERATURE: float = 0.7

    # Quota limits (free tier)
    GROQ_DAILY_TOKEN_LIMIT: int = 500_000
    DAILY_TOKEN_BUDGET: int = 500_000
    DAILY_REQUEST_BUDGET: int = 2000
    PER_USER_DAILY_BLUEPRINTS: int = 3

    # CORS / Frontend
    FRONTEND_URL: str = "http://localhost:3000"

    # Render / Deployment
    RENDER_EXTERNAL_URL: Optional[str] = None
    PORT: int = 8000

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()