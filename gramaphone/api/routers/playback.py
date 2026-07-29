from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional
import uuid

from api.dependencies.database import get_db
from api.dependencies.auth import get_current_profile
from api.models import ListeningHistory, Profile
from sqlalchemy import select, func
from datetime import datetime

router = APIRouter(prefix="/playback", tags=["playback"])


class QueueRequest(BaseModel):
    track_id: str
    source: str = "itunes"  # itunes, youtube
    video_id: Optional[str] = None


class PlaybackCompleteRequest(BaseModel):
    track_id: str
    title: str
    artist: str
    album: Optional[str] = None
    artwork_url: Optional[str] = None
    video_id: Optional[str] = None
    completed: bool
    skipped: bool
    play_duration_sec: int
    track_duration_sec: int


@router.post("/queue")
async def queue_track(
    req: QueueRequest,
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    """Queue a track for playback (returns YouTube stream URL)."""
    # In production: call yt-dlp to get stream URL
    # For now, return placeholder
    return {
        "stream_url": f"https://youtube.com/watch?v={req.video_id or 'PLACEHOLDER'}",
        "track_id": req.track_id
    }


@router.post("/complete")
async def complete_track(
    req: PlaybackCompleteRequest,
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    """Log playback completion and update runtime stats."""
    # Log to history
    history = ListeningHistory(
        profile_id=profile.id,
        track_id=req.track_id,
        title=req.title,
        artist=req.artist,
        album=req.album,
        art_url=req.artwork_url,
        video_id=req.video_id,
        completed=req.completed,
        skipped=req.skipped,
        play_duration_sec=req.play_duration_sec,
        track_duration_sec=req.track_duration_sec,
        played_at=datetime.utcnow()
    )
    db.add(history)
    
    # Update blueprint runtime stats
    from api.services.blueprint_service import update_blueprint_runtime
    await update_blueprint_runtime(profile.id, db, req.completed, req.skipped)
    
    await db.commit()
    return {"status": "logged"}


@router.get("/history")
async def get_history(
    limit: int = 50,
    offset: int = 0,
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    """Get recent listening history."""
    result = await db.execute(
        select(ListeningHistory)
        .where(ListeningHistory.profile_id == profile.id)
        .order_by(ListeningHistory.played_at.desc())
        .limit(limit)
        .offset(offset)
    )
    history = result.scalars().all()
    return [
        {
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
        }
        for h in history
    ]


@router.get("/stats")
async def get_stats(
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    """Get playback statistics."""
    from api.services.affinity_service import get_completion_stats, get_listening_streak
    
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
    
    return {
        "total_plays": total_plays,
        "unique_artists": unique_artists,
        "completion_rate": round(completion_rate, 1),
        "skip_rate": round(skip_rate, 1),
        "listening_streak": streak
    }