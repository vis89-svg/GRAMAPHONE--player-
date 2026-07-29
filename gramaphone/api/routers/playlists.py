import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional, List
import uuid

from api.dependencies.database import get_db
from api.dependencies.auth import get_current_profile
from api.models import Profile, Playlist, PlaylistTrack, ListeningHistory, DailyBlueprint
from api.services.playlist_service import (
    create_playlist, get_playlist, get_user_playlists, 
    smart_merge_playlist, refresh_auto_playlist, add_tracks_to_playlist
)
from api.services.affinity_service import (
    get_top_affinity_artists, get_taste_profile, get_recent_plays,
    get_completion_stats
)
from api.services.search_service import SearchService
from api.services.blueprint_service import blueprint_service

router = APIRouter(prefix="/playlists", tags=["playlists"])


class PlaylistCreate(BaseModel):
    name: str
    source: str = "user"
    tracks: List[dict] = []


class PlaylistUpdate(BaseModel):
    name: Optional[str] = None


class TrackAdd(BaseModel):
    track_id: Optional[str] = None
    title: str
    artist: str
    album: Optional[str] = None
    artwork_url: Optional[str] = None


class AIPlaylistRequest(BaseModel):
    prompt: str
    count: int = 15


AI_PLAYLIST_SYSTEM = """You are a music playlist curator. Given a user's request and their listening profile, generate a list of real songs as JSON.

Rules:
- Output ONLY valid JSON array of objects with "artist" and "title" fields
- Each track must be a REAL, existing song
- Match the user's requested mood/genre/theme
- Use the user's listening profile for personalization
- Recommend at most {count} tracks"""

AI_PLAYLIST_USER = """User Request: {prompt}

User Profile:
- Top Artists: {top_artists}
- Top Genres: {top_genres}
- Recent Plays: {recent_plays}

Generate {count} real tracks as a JSON array: [{{"artist": "...", "title": "..."}}, ...]"""


@router.post("/ai-generate")
async def ai_generate_playlist(
    data: AIPlaylistRequest,
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    """Generate a playlist using AI based on a text prompt + user profile."""
    from openai import AsyncOpenAI
    import instructor
    from pydantic import BaseModel, Field

    if not blueprint_service._get_client():
        raise HTTPException(503, "AI service not available (no Groq API key)")

    class AITrack(BaseModel):
        artist: str
        title: str

    class AIPlaylistResponse(BaseModel):
        tracks: list[AITrack] = Field(min_items=5, max_items=25)
        name: str

    # Gather user context
    top_artists = []
    top_genres = []
    recent_plays = []
    try:
        top_artists = await get_top_affinity_artists(db, profile.id, 5)
    except Exception:
        pass
    try:
        top_genres = await get_taste_profile(db, profile.id, 3)
    except Exception:
        pass
    try:
        recent_plays = await get_recent_plays(db, profile.id, 10)
    except Exception:
        pass

    client = blueprint_service._get_client()
    try:
        response = await client.chat.completions.create(
            model=blueprint_service.model,
            response_model=AIPlaylistResponse,
            messages=[
                {"role": "system", "content": AI_PLAYLIST_SYSTEM.format(count=data.count)},
                {"role": "user", "content": AI_PLAYLIST_USER.format(
                    prompt=data.prompt,
                    top_artists=json.dumps(top_artists),
                    top_genres=json.dumps(top_genres),
                    recent_plays=json.dumps(recent_plays),
                    count=data.count,
                )}
            ],
            temperature=0.8,
            max_tokens=2048
        )

        # Hydrate tracks with iTunes metadata
        search = SearchService()
        hydrated = []
        for t in response.tracks:
            try:
                it = await search.search_tracks(f"{t.artist} {t.title}", limit=1)
                if it:
                    tt = it[0]
                    hydrated.append({
                        "track_id": tt.track_id,
                        "title": tt.title,
                        "artist": tt.artist,
                        "album": tt.album,
                        "artwork_url": tt.artwork_url,
                        "duration_ms": tt.duration_ms,
                    })
                else:
                    hydrated.append({"title": t.title, "artist": t.artist})
            except Exception:
                hydrated.append({"title": t.title, "artist": t.artist})

        # Create the playlist
        playlist = await create_playlist(db, profile.id, response.name, "ai_generated", hydrated)
        await db.commit()

        return {
            "id": str(playlist.id),
            "name": playlist.name,
            "track_count": len(hydrated),
            "tracks": hydrated
        }

    except Exception as e:
        raise HTTPException(500, f"AI playlist generation failed: {e}")


@router.post("", response_model=dict)
async def create_playlist_endpoint(
    data: PlaylistCreate,
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    playlist = await create_playlist(db, profile.id, data.name, data.source, data.tracks)
    await db.commit()
    return {"id": str(playlist.id), "name": playlist.name, "source": playlist.source}


@router.get("")
async def list_playlists(
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    playlists = await get_user_playlists(db, profile.id)
    result = []
    for p in playlists:
        count_result = await db.execute(
            select(func.count()).where(PlaylistTrack.playlist_id == p.id)
        )
        result.append({
            "id": str(p.id),
            "name": p.name,
            "source": p.source,
            "track_count": count_result.scalar() or 0,
            "created_at": p.created_at
        })
    return result


@router.get("/{playlist_id}")
async def get_playlist_endpoint(
    playlist_id: uuid.UUID,
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    playlist = await get_playlist(db, playlist_id, profile.id)
    if not playlist:
        raise HTTPException(404, "Playlist not found")
    
    tracks_result = await db.execute(
        select(PlaylistTrack)
        .where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position)
    )
    tracks = tracks_result.scalars().all()
    
    return {
        "id": str(playlist.id),
        "name": playlist.name,
        "source": playlist.source,
        "tracks": [
            {
                "id": str(t.id),
                "track_id": t.track_id,
                "title": t.title,
                "artist": t.artist,
                "album": t.album,
                "artwork_url": t.art_url,
                "position": t.position
            }
            for t in tracks
        ]
    }


@router.put("/{playlist_id}")
async def update_playlist(
    playlist_id: uuid.UUID,
    data: PlaylistUpdate,
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    playlist = await get_playlist(db, playlist_id, profile.id)
    if not playlist:
        raise HTTPException(404, "Playlist not found")
    
    if data.name:
        playlist.name = data.name
    
    await db.commit()
    return {"status": "updated"}


@router.post("/{playlist_id}/tracks")
async def add_tracks(
    playlist_id: uuid.UUID,
    tracks: List[TrackAdd],
    smart: bool = True,
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    playlist = await get_playlist(db, playlist_id, profile.id)
    if not playlist:
        raise HTTPException(404, "Playlist not found")
    
    if smart:
        result = await smart_merge_playlist(db, playlist_id, [t.model_dump() for t in tracks])
    else:
        result = {"added": await add_tracks_to_playlist(db, playlist_id, [t.model_dump() for t in tracks])}
    
    await db.commit()
    return result


@router.delete("/{playlist_id}")
async def delete_playlist(
    playlist_id: uuid.UUID,
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    from api.services.playlist_service import delete_playlist
    await delete_playlist(db, playlist_id, profile.id)
    await db.commit()
    return {"status": "deleted"}


@router.post("/{playlist_id}/smart-refresh")
async def smart_refresh(
    playlist_id: uuid.UUID,
    new_tracks: List[TrackAdd],
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    """Smart merge: keep loved tracks, replace stale ones."""
    result = await smart_merge_playlist(db, playlist_id, [t.model_dump() for t in new_tracks])
    await db.commit()
    return result