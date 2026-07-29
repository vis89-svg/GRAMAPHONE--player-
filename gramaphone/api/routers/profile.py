from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
import uuid

from api.dependencies.database import get_db
from api.dependencies.auth import get_current_profile
from api.models import Profile, ListeningHistory, ArtistAffinity, TasteProfile, DailyBlueprint, Playlist
from api.services.affinity_service import (
    get_top_affinity_artists, get_taste_profile, get_completion_stats,
    get_tod_genres, get_listening_streak, recalculate_affinities,
    recalculate_taste_profile
)

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
async def get_profile(
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    return {
        "id": str(profile.id),
        "user_id": str(profile.user_id),
        "name": profile.name,
        "languages": profile.languages,
        "fav_artists": profile.fav_artists,
        "created_at": profile.created_at
    }


@router.put("")
async def update_profile(
    data: dict,
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    for key, value in data.items():
        if value is not None and hasattr(profile, key):
            setattr(profile, key, value)
    await db.commit()
    return {"status": "updated", "profile": {
        "id": str(profile.id),
        "name": profile.name,
        "languages": profile.languages,
        "fav_artists": profile.fav_artists
    }}


@router.get("/stats")
async def get_profile_stats(
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    completion_rate, skip_rate = await get_completion_stats(db, profile.id)
    streak = await get_listening_streak(db, profile.id)
    
    # Total plays
    total_result = await db.execute(
        select(func.count()).where(ListeningHistory.profile_id == profile.id)
    )
    total_plays = total_result.scalar() or 0
    
    # Unique artists
    artists_result = await db.execute(
        select(func.count(func.distinct(ListeningHistory.artist)))
        .where(ListeningHistory.profile_id == profile.id)
    )
    unique_artists = artists_result.scalar() or 0
    
    # Top artists
    top_artists = await get_top_affinity_artists(db, profile.id, 10)
    
    # Top genres
    top_genres = await get_taste_profile(db, profile.id, 10)
    
    # Playlists count
    playlists_result = await db.execute(
        select(func.count()).where(Playlist.profile_id == profile.id)
    )
    playlists_count = playlists_result.scalar() or 0
    
    return {
        "total_plays": total_plays,
        "unique_artists": unique_artists,
        "playlists_count": playlists_count,
        "completion_rate": round(completion_rate, 1),
        "skip_rate": round(skip_rate, 1),
        "listening_streak": streak,
        "top_artists": top_artists,
        "top_genres": top_genres
    }


@router.get("/affinity")
async def get_affinity(
    limit: int = Query(50, le=200),
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    artists = await get_top_affinity_artists(db, profile.id, limit)
    return {"artists": artists}


@router.get("/taste")
async def get_taste(
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    genres = await get_taste_profile(db, profile.id, 20)
    tod = await get_tod_genres(db, profile.id)
    return {"genres": genres, "time_of_day": tod}


@router.post("/recalculate")
async def recalculate_profile(
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    """Manually trigger affinity & taste profile recalculation."""
    affinity_count = await recalculate_affinities(db, profile.id)
    taste_count = await recalculate_taste_profile(db, profile.id)
    await db.commit()
    return {
        "status": "recalculated",
        "artists_updated": affinity_count,
        "genres_updated": taste_count
    }


@router.get("/history")
async def get_history(
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    days: int = Query(30, le=365),
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    from datetime import datetime, timedelta
    since = datetime.utcnow() - timedelta(days=days)
    
    result = await db.execute(
        select(ListeningHistory)
        .where(
            ListeningHistory.profile_id == profile.id,
            ListeningHistory.played_at >= since
        )
        .order_by(ListeningHistory.played_at.desc())
        .limit(limit)
        .offset(offset)
    )
    history = result.scalars().all()
    
    return [{
        "id": h.id,
        "title": h.title,
        "artist": h.artist,
        "album": h.album,
        "artwork_url": h.art_url,
        "completed": h.completed,
        "skipped": h.skipped,
        "play_duration_sec": h.play_duration_sec,
        "track_duration_sec": h.track_duration_sec,
        "played_at": h.played_at
    } for h in history]


@router.get("/blueprints")
async def get_blueprints(
    limit: int = Query(30, le=90),
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(DailyBlueprint)
        .where(DailyBlueprint.profile_id == profile.id)
        .order_by(DailyBlueprint.date.desc())
        .limit(limit)
    )
    blueprints = result.scalars().all()
    
    return [{
        "id": str(b.id),
        "date": b.date.isoformat(),
        "strategy": b.strategy,
        "runtime_stats": b.runtime_stats,
        "llm_tokens_used": b.llm_tokens_used
    } for b in blueprints]