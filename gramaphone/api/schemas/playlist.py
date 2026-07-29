from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid


class PlaylistTrackBase(BaseModel):
    track_id: Optional[str] = None
    title: str
    artist: str
    album: Optional[str] = None
    art_url: Optional[str] = None


class PlaylistTrackAdd(PlaylistTrackBase):
    pass


class PlaylistTrackResponse(PlaylistTrackBase):
    id: int
    position: int
    playlist_id: uuid.UUID

    class Config:
        from_attributes = True


class PlaylistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    source: str = Field(default="user", pattern="^(user|auto_daily|auto_forgotten|auto_loved|auto_gems|genre|discover)$")


class PlaylistResponse(BaseModel):
    id: uuid.UUID
    name: str
    source: str
    created_at: datetime
    updated_at: datetime
    tracks: List[PlaylistTrackResponse] = []

    class Config:
        from_attributes = True


class PlaylistListResponse(BaseModel):
    id: uuid.UUID
    name: str
    source: str
    created_at: datetime
    track_count: int = 0

    class Config:
        from_attributes = True