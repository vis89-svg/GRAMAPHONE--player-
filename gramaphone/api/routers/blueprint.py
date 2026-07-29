from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.database import get_db
from api.dependencies.auth import get_current_profile
from api.models import Profile
from api.services.blueprint_service import blueprint_service

router = APIRouter(prefix="/blueprint", tags=["blueprint"])


@router.post("/generate")
async def generate_blueprint(
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    """Manually trigger blueprint generation for today."""
    bp = await blueprint_service.generate_blueprint(db, profile.id)
    return {
        "id": str(bp.id),
        "date": bp.date.isoformat(),
        "strategy": bp.strategy,
        "seed_tracks": bp.seed_tracks,
        "playlist_updates": bp.playlist_updates
    }


@router.get("/today")
async def get_today_blueprint(
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    bp = await blueprint_service.generate_blueprint(db, profile.id)
    if not bp:
        return {"message": "No blueprint available"}
    return {
        "id": str(bp.id),
        "date": bp.date.isoformat(),
        "strategy": bp.strategy,
        "seed_tracks": bp.seed_tracks,
        "playlist_updates": bp.playlist_updates,
        "runtime_stats": bp.runtime_stats
    }


@router.post("/refresh-playlists")
async def refresh_auto_playlists(
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    """Trigger auto playlist refresh based on today's blueprint."""
    from api.services.playlist_service import run_nightly_playlist_refresh
    
    # Generate blueprint if needed
    bp = await blueprint_service.generate_blueprint(db, profile.id)
    
    # Run playlist refresh for this profile
    # (simplified - just refresh the 4 auto playlists)
    from api.services.playlist_service import (
        generate_daily_mix, generate_forgotten_favorites,
        generate_recently_loved, generate_hidden_gems,
        refresh_auto_playlist
    )
    
    bp_data = {
        "seed_tracks": bp.seed_tracks,
        "strategy": bp.strategy
    }
    
    results = {}
    
    results["daily_mix"] = await refresh_auto_playlist(
        db, profile.id, "Daily Mix",
        await generate_daily_mix(db, profile.id, bp_data),
        "auto_daily"
    )
    
    results["forgotten_favorites"] = await refresh_auto_playlist(
        db, profile.id, "Forgotten Favorites",
        await generate_forgotten_favorites(db, profile.id),
        "auto_forgotten"
    )
    
    results["recently_loved"] = await refresh_auto_playlist(
        db, profile.id, "Recently Loved",
        await generate_recently_loved(db, profile.id),
        "auto_loved"
    )
    
    results["hidden_gems"] = await refresh_auto_playlist(
        db, profile.id, "Hidden Gems",
        await generate_hidden_gems(db, profile.id),
        "auto_gems"
    )
    
    await db.commit()
    return {"refreshed": results}