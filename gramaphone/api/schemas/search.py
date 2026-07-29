from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date


# ===== SEARCH MODELS =====

class Track(BaseModel):
    track_id: str
    title: str
    artist: str
    album: str
    artist_id: str
    album_id: str
    artwork_url: str = ""
    duration_ms: int = 0
    genre: str = ""
    release_date: str = ""
    track_number: int = 0
    disc_number: int = 1
    explicit: bool = False
    preview_url: Optional[str] = None

    @property
    def duration_str(self) -> str:
        mins, secs = divmod(self.duration_ms // 1000, 60)
        return f"{mins}:{secs:02d}"


class Album(BaseModel):
    album_id: str
    title: str
    artist: str
    artist_id: str
    artwork_url: str = ""
    release_date: str = ""
    track_count: int = 0
    genre: str = ""
    copyright: str = ""


class Artist(BaseModel):
    artist_id: str
    name: str
    genre: str = ""
    artwork_url: str = ""


class Playlist(BaseModel):
    playlist_id: str
    title: str
    creator: str
    track_count: int
    artwork_url: str = ""
    description: str = ""


class SearchResult(BaseModel):
    tracks: List[Track] = []
    albums: List[Album] = []
    artists: List[Artist] = []
    playlists: List[Playlist] = []


class AlbumTracksResponse(BaseModel):
    album: Album
    tracks: List[Track]


class AlbumTrackWithYT(BaseModel):
    track_id: str = ""
    title: str
    artist: str = ""
    duration_ms: int = 0
    artwork_url: str = ""
    track_number: int = 0
    youtube_video_id: Optional[str] = None
    youtube_title: Optional[str] = None
    youtube_channel: Optional[str] = None
    youtube_duration: int = 0


class AlbumWithYTResponse(BaseModel):
    album: Album
    tracks: List[AlbumTrackWithYT]
    source: str = "itunes"


# ===== YOUTUBE MODELS =====

class YouTubeVersion(BaseModel):
    video_id: str
    title: str
    channel: str
    duration: int
    artwork_url: str = ""
    score: int = 0

    @property
    def stream_url(self) -> str:
        return f"https://youtube.com/watch?v={self.video_id}"


class YouTubeSearchResult(BaseModel):
    versions: List[YouTubeVersion]
    best_version: Optional[YouTubeVersion] = None


# ===== REQUEST/RESPONSE =====

class SearchQuery(BaseModel):
    q: str = Field(..., min_length=1, max_length=200)
    type: str = Field(default="all", pattern="^(all|track|album|artist|playlist)$")
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchSuggestionsResponse(BaseModel):
    suggestions: List[str]