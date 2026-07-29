import httpx
import re
import asyncio
from typing import Optional
from dataclasses import dataclass
from api.config import settings


@dataclass
class Track:
    track_id: str
    title: str
    artist: str
    album: str
    artist_id: str
    album_id: str
    artwork_url: str
    duration_ms: int
    genre: str
    release_date: str
    track_number: int
    disc_number: int
    explicit: bool
    preview_url: Optional[str] = None


@dataclass
class Album:
    album_id: str
    title: str
    artist: str
    artist_id: str
    artwork_url: str
    release_date: str
    track_count: int
    genre: str
    copyright: str


@dataclass
class Artist:
    artist_id: str
    name: str
    genre: str
    artwork_url: str


class SearchService:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=10.0, follow_redirects=True)
        self.base_url = settings.ITUNES_BASE_URL

    async def close(self):
        await self.client.aclose()

    # ===== SEARCH ENDPOINTS =====

    async def search_all(self, query: str, limit: int = 20) -> dict:
        """Unified search across all types."""
        results = await asyncio.gather(
            self.search_tracks(query, limit),
            self.search_albums(query, limit),
            self.search_artists(query, limit),
            self.search_playlists(query, limit),
            return_exceptions=True
        )
        return {
            "tracks": results[0] if not isinstance(results[0], Exception) else [],
            "albums": results[1] if not isinstance(results[1], Exception) else [],
            "artists": results[2] if not isinstance(results[2], Exception) else [],
            "playlists": results[3] if not isinstance(results[3], Exception) else [],
        }

    async def search_tracks(self, query: str, limit: int = 20) -> list[Track]:
        params = {"term": query, "entity": "song", "limit": limit, "media": "music"}
        data = await self._get("/search", params)
        return [self._parse_track(t) for t in data.get("results", []) if t.get("wrapperType") == "track"]

    async def search_albums(self, query: str, limit: int = 20) -> list[Album]:
        params = {"term": query, "entity": "album", "limit": limit, "media": "music"}
        data = await self._get("/search", params)
        return [self._parse_album(a) for a in data.get("results", []) if a.get("wrapperType") == "collection"]

    async def search_artists(self, query: str, limit: int = 10) -> list[Artist]:
        params = {"term": query, "entity": "musicArtist", "limit": limit, "media": "music"}
        data = await self._get("/search", params)
        return [self._parse_artist(a) for a in data.get("results", []) if a.get("wrapperType") == "artist"]

    async def search_playlists(self, query: str, limit: int = 10) -> list[dict]:
        """Search Deezer playlists."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.DEEZER_BASE_URL}/search/playlist",
                params={"q": query, "limit": limit}
            )
        return resp.json().get("data", [])

    # ===== ALBUM-SCOPED SEARCH (KEY FIX) =====

    async def get_album_tracks(self, album_id: str) -> list[Track]:
        """Get ONLY tracks from a specific album (no live/cover duplicates from other albums)."""
        params = {"id": album_id, "entity": "song"}
        data = await self._get("/lookup", params)
        tracks = []
        for item in data.get("results", [])[1:]:  # Skip first (album itself)
            if item.get("collectionId") == int(album_id):
                tracks.append(self._parse_track(item))
        # Sort by track number
        tracks.sort(key=lambda t: (t.disc_number, t.track_number))
        return tracks

    async def get_album_by_id(self, album_id: str) -> Optional[Album]:
        params = {"id": album_id, "entity": "album"}
        data = await self._get("/lookup", params)
        results = data.get("results", [])
        if results:
            return self._parse_album(results[0])
        return None

    # ===== ARTIST DETAIL =====

    async def get_artist_albums(self, artist_id: str, limit: int = 20) -> list[Album]:
        params = {"id": artist_id, "entity": "album", "limit": limit}
        data = await self._get("/lookup", params)
        return [self._parse_album(a) for a in data.get("results", [])[1:] if a.get("wrapperType") == "collection"]

    async def get_artist_top_tracks(self, artist_id: str, limit: int = 20) -> list[Track]:
        params = {"id": artist_id, "entity": "song", "limit": limit}
        data = await self._get("/lookup", params)
        return [self._parse_track(t) for t in data.get("results", [])[1:] if t.get("wrapperType") == "track"]

    # ===== SUGGESTIONS / AUTOCOMPLETE =====

    async def get_suggestions(self, prefix: str, limit: int = 10) -> list[str]:
        """iTunes autocomplete (undocumented but works)."""
        try:
            resp = await self.client.get(
                f"{self.base_url}/search",
                params={"term": prefix, "entity": "song", "limit": limit, "attribute": "songTerm"}
            )
            data = resp.json()
            return list(set(t.get("trackName", "") for t in data.get("results", []) if t.get("trackName")))
        except Exception:
            return []

    # ===== ARTIST GENRE LOOKUP (for taste profile) =====

    async def get_artist_genre(self, artist_name: str) -> Optional[str]:
        """Get primary genre for an artist via iTunes search."""
        try:
            data = await self._get("/search", {"term": artist_name, "entity": "musicArtist", "limit": 1})
            results = data.get("results", [])
            if results:
                return results[0].get("primaryGenreName", "")
        except Exception:
            pass
        return None

    # ===== INTERNAL =====

    async def _get(self, path: str, params: dict) -> dict:
        resp = await self.client.get(f"{self.base_url}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    def _parse_track(self, data: dict) -> Track:
        return Track(
            track_id=str(data.get("trackId", "")),
            title=data.get("trackName", ""),
            artist=data.get("artistName", ""),
            album=data.get("collectionName", ""),
            artist_id=str(data.get("artistId", "")),
            album_id=str(data.get("collectionId", "")),
            artwork_url=self._resize_artwork(data.get("artworkUrl100", ""), 600),
            duration_ms=data.get("trackTimeMillis", 0),
            genre=data.get("primaryGenreName", ""),
            release_date=data.get("releaseDate", "")[:10],
            track_number=data.get("trackNumber", 0),
            disc_number=data.get("discNumber", 1),
            explicit=data.get("trackExplicitness", "") == "explicit",
            preview_url=data.get("previewUrl"),
        )

    def _parse_album(self, data: dict) -> Album:
        return Album(
            album_id=str(data.get("collectionId", "")),
            title=data.get("collectionName", ""),
            artist=data.get("artistName", ""),
            artist_id=str(data.get("artistId", "")),
            artwork_url=self._resize_artwork(data.get("artworkUrl100", ""), 600),
            release_date=data.get("releaseDate", "")[:10],
            track_count=data.get("trackCount", 0),
            genre=data.get("primaryGenreName", ""),
            copyright=data.get("copyright", ""),
        )

    def _parse_artist(self, data: dict) -> Artist:
        return Artist(
            artist_id=str(data.get("artistId", "")),
            name=data.get("artistName", ""),
            genre=data.get("primaryGenreName", ""),
            artwork_url=self._resize_artwork(data.get("artworkUrl100", ""), 600),
        )

    def _resize_artwork(self, url: str, size: int) -> str:
        if not url:
            return ""
        return re.sub(r"\d+x\d+", f"{size}x{size}", url)


# ===== YOUTUBE VERSION SELECTOR (KEY FIX) =====

YT_PRIORITY_PATTERNS = [
    (r"Topic$", 100),           # "Artist - Title Topic" (YouTube Music official)
    (r"lyrics?", 90),           # Lyric videos
    (r"audio", 80),             # Audio-only uploads
    (r"official audio", 70),    # Official channel audio
    (r"visualizer", 60),        # Visualizers
    (r"official video", 30),    # Music videos (lower - has intros/outros)
    (r"live", -50),             # Penalize live
    (r"cover", -50),            # Penalize covers
    (r"remix", -30),            # Penalize remixes (unless requested)
    (r"VEVO", -20),             # VEVO often has ads/intros
]

BLOCKED_PATTERNS = [
    r"karaoke",
    r"instrumental",
    r"8d audio",
    r"bass boosted",
    r"nightcore",
    r"sped up",
    r"slowed",
]


def score_yt_result(title: str, channel: str, duration: int, target_duration: int) -> int:
    """Score a YouTube result. Higher = better."""
    score = 0
    title_lower = title.lower()
    channel_lower = channel.lower()

    # Channel bonuses
    if "topic" in channel_lower:
        score += 50
    if "official" in channel_lower or "music" in channel_lower:
        score += 20

    # Title pattern scoring
    for pattern, weight in YT_PRIORITY_PATTERNS:
        if re.search(pattern, title_lower, re.IGNORECASE):
            score += weight

    # Blocked patterns
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, title_lower, re.IGNORECASE):
            score -= 100

    # Duration match (prefer within 10% of target)
    if target_duration > 0 and duration > 0:
        diff_pct = abs(duration - target_duration) / target_duration
        if diff_pct < 0.1:
            score += 20
        elif diff_pct < 0.2:
            score += 10
        elif diff_pct > 0.5:
            score -= 30

    return score


def pick_best_yt_version(
    results: list[dict], 
    target_duration: int = 0,
    prefer_lyrics: bool = True
) -> Optional[dict]:
    """Select best YouTube version from yt-dlp search results."""
    if not results:
        return None

    scored = []
    for r in results:
        title = r.get("title", "")
        channel = r.get("channel", r.get("uploader", ""))
        duration = r.get("duration", 0)
        score = score_yt_result(title, channel, duration, target_duration)
        scored.append((score, r))

    scored.sort(key=lambda x: -x[0])
    return scored[0][1] if scored else None