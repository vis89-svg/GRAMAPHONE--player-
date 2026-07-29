from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Optional, List
import uuid

from api.dependencies.database import get_db
from api.dependencies.auth import get_current_profile
from api.models import Profile, Playlist, PlaylistTrack, ListeningHistory
from api.services.playlist_service import (
    create_playlist, get_playlist, get_user_playlists, 
    smart_merge_playlist, refresh_auto_playlist
)
from api.services.affinity_service import get_collaborative_recommendations

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
        # Simple add
        from api.services.playlist_service import add_tracks_to_playlist
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