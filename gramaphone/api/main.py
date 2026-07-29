from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.config import settings
from api.dependencies.database import init_db, close_db
from api.routers import auth, search, playback, playlists, recommendations, blueprint, profile
from api.tasks.scheduler import start_scheduler, shutdown_scheduler
from api.services.quota_service import quota_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    
    # Initialize quota service (Redis)
    if settings.UPSTASH_REDIS_REST_URL and settings.UPSTASH_REDIS_REST_TOKEN:
        await quota_service.init(
            settings.UPSTASH_REDIS_REST_URL,
            settings.UPSTASH_REDIS_REST_TOKEN
        )
    
    # Start background scheduler
    start_scheduler()
    
    yield
    
    # Shutdown
    shutdown_scheduler()
    await close_db()


app = FastAPI(
    title="Gramaphone API",
    description="Personalized music streaming API with AI-powered daily blueprints",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(playback.router, prefix="/api/v1")
app.include_router(playlists.router, prefix="/api/v1")
app.include_router(recommendations.router, prefix="/api/v1")
app.include_router(blueprint.router, prefix="/api/v1")
app.include_router(profile.router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "gramaphone-api"}


import os
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")