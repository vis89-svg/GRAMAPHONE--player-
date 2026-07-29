"""
Tkinter API Adapter - Bridges the legacy music_app.py to the new FastAPI backend.
Drop-in replacement for direct service calls.
"""
import os
import httpx
import asyncio
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class ApiTrack:
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
class ApiAlbum:
    album_id: str
    title: str
    artist: str
    artist_id: str
    artwork_url: str
    release_date: str
    track_count: int
    genre: str
    copyright: str


class ApiClient:
    def __init__(self, base_url: str = "http://localhost:8000/api/v1"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=30.0)
        self._token: Optional[str] = None
        self._profile_id: Optional[str] = None

    async def login(self, email: str, password: str) -> dict:
        resp = await self.client.post(
            f"{self.base_url}/auth/login",
            data={"username": email, "password": password}
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        return data

    async def register(self, email: str, password: str) -> dict:
        resp = await self.client.post(
            f"{self.base_url}/auth/register",
            json={"email": email, "password": password}
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        return data

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    # ===== SEARCH =====

    async def search_all(self, query: str, limit: int = 20) -> dict:
        resp = await self.client.get(
            f"{self.base_url}/search",
            params={"q": query, "type": "all", "limit": limit},
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    async def search_tracks(self, query: str, limit: int = 20) -> List[ApiTrack]:
        resp = await self.client.get(
            f"{self.base_url}/search",
            params={"q": query, "type": "track", "limit": limit},
            headers=self._headers()
        )
        resp.raise_for_status()
        data = resp.json()
        return [ApiTrack(**t) for t in data.get("tracks", [])]

    async def search_albums(self, query: str, limit: int = 20) -> List[ApiAlbum]:
        resp = await self.client.get(
            f"{self.base_url}/search",
            params={"q": query, "type": "album", "limit": limit},
            headers=self._headers()
        )
        resp.raise_for_status()
        data = resp.json()
        return [ApiAlbum(**a) for a in data.get("albums", [])]

    async def get_album_tracks(self, album_id: str) -> List[ApiTrack]:
        """KEY FIX: Get ONLY tracks from a specific album."""
        resp = await self.client.get(
            f"{self.base_url}/search/album/{album_id}/tracks",
            headers=self._headers()
        )
        resp.raise_for_status()
        data = resp.json()
        return [ApiTrack(**t) for t in data.get("tracks", [])]

    async def get_youtube_versions(self, artist: str, title: str, album: str = "", duration_ms: int = 0) -> dict:
        """Get YouTube versions ranked by quality (Topic > lyrics > audio)."""
        resp = await self.client.get(
            f"{self.base_url}/search/youtube/versions",
            params={"artist": artist, "title": title, "album": album, "duration_ms": duration_ms},
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    # ===== PLAYBACK =====

    async def queue_track(self, track_id: str, video_id: str = None) -> dict:
        resp = await self.client.post(
            f"{self.base_url}/playback/queue",
            json={"track_id": track_id, "source": "youtube", "video_id": video_id},
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    async def complete_track(
        self, 
        track_id: str, title: str, artist: str, album: str,
        artwork_url: str, video_id: str,
        completed: bool, skipped: bool,
        play_duration_sec: int, track_duration_sec: int
    ) -> dict:
        resp = await self.client.post(
            f"{self.base_url}/playback/complete",
            json={
                "track_id": track_id, "title": title, "artist": artist, "album": album,
                "artwork_url": artwork_url, "video_id": video_id,
                "completed": completed, "skipped": skipped,
                "play_duration_sec": play_duration_sec, "track_duration_sec": track_duration_sec
            },
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    async def get_history(self, limit: int = 50) -> List[dict]:
        resp = await self.client.get(
            f"{self.base_url}/playback/history",
            params={"limit": limit},
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    async def get_stats(self) -> dict:
        resp = await self.client.get(
            f"{self.base_url}/playback/stats",
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    # ===== PLAYLISTS =====

    async def get_playlists(self) -> List[dict]:
        resp = await self.client.get(
            f"{self.base_url}/playlists",
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    async def get_playlist(self, playlist_id: str) -> dict:
        resp = await self.client.get(
            f"{self.base_url}/playlists/{playlist_id}",
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    async def create_playlist(self, name: str, source: str = "user", tracks: List[dict] = None) -> dict:
        resp = await self.client.post(
            f"{self.base_url}/playlists",
            json={"name": name, "source": source, "tracks": tracks or []},
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    async def add_tracks(self, playlist_id: str, tracks: List[dict], smart: bool = True) -> dict:
        resp = await self.client.post(
            f"{self.base_url}/playlists/{playlist_id}/tracks",
            json={"tracks": tracks, "smart": smart},
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    async def smart_refresh(self, playlist_id: str, new_tracks: List[dict]) -> dict:
        resp = await self.client.post(
            f"{self.base_url}/playlists/{playlist_id}/smart-refresh",
            json={"new_tracks": new_tracks},
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    # ===== RECOMMENDATIONS / HOME =====

    async def get_home(self) -> dict:
        resp = await self.client.get(
            f"{self.base_url}/recommendations/home",
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    # ===== BLUEPRINT =====

    async def get_blueprint(self) -> Optional[dict]:
        resp = await self.client.get(
            f"{self.base_url}/recommendations/blueprint",
            headers=self._headers()
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    # ===== PROFILE =====

    async def get_profile(self) -> dict:
        resp = await self.client.get(
            f"{self.base_url}/auth/me",
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    async def update_profile(self, name: str = None, languages: List[str] = None, fav_artists: List[str] = None) -> dict:
        data = {}
        if name: data["name"] = name
        if languages: data["languages"] = languages
        if fav_artists: data["fav_artists"] = fav_artists
        
        resp = await self.client.put(
            f"{self.base_url}/auth/me",
            json=data,
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    async def onboarding_step1(self, languages: List[str]) -> dict:
        resp = await self.client.post(
            f"{self.base_url}/auth/onboarding/step1",
            json={"languages": languages},
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    async def onboarding_step2(self, artists: List[str]) -> dict:
        resp = await self.client.post(
            f"{self.base_url}/auth/onboarding/step2",
            json={"artists": artists},
            headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self.client.aclose()


# ===== SYNC WRAPPER FOR TKINTER =====

class SyncApiClient:
    """Synchronous wrapper for Tkinter (runs async in thread pool)."""
    
    def __init__(self, base_url: str = "http://localhost:8000/api/v1"):
        self._async = ApiClient(base_url)
        self._loop = None

    def _run(self, coro):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

    def login(self, email: str, password: str) -> dict:
        return self._run(self._async.login(email, password))

    def register(self, email: str, password: str) -> dict:
        return self._run(self._async.register(email, password))

    def search_all(self, query: str, limit: int = 20) -> dict:
        return self._run(self._async.search_all(query, limit))

    def search_tracks(self, query: str, limit: int = 20) -> List[ApiTrack]:
        return self._run(self._async.search_tracks(query, limit))

    def search_albums(self, query: str, limit: int = 20) -> List[ApiAlbum]:
        return self._run(self._async.search_albums(query, limit))

    def get_album_tracks(self, album_id: str) -> List[ApiTrack]:
        return self._run(self._async.get_album_tracks(album_id))

    def get_youtube_versions(self, artist: str, title: str, album: str = "", duration_ms: int = 0) -> dict:
        return self._run(self._async.get_youtube_versions(artist, title, album, duration_ms))

    def queue_track(self, track_id: str, video_id: str = None) -> dict:
        return self._run(self._async.queue_track(track_id, video_id))

    def complete_track(self, **kwargs) -> dict:
        return self._run(self._async.complete_track(**kwargs))

    def get_history(self, limit: int = 50) -> List[dict]:
        return self._run(self._async.get_history(limit))

    def get_stats(self) -> dict:
        return self._run(self._async.get_stats())

    def get_playlists(self) -> List[dict]:
        return self._run(self._async.get_playlists())

    def get_playlist(self, playlist_id: str) -> dict:
        return self._run(self._async.get_playlist(playlist_id))

    def create_playlist(self, name: str, source: str = "user", tracks: List[dict] = None) -> dict:
        return self._run(self._async.create_playlist(name, source, tracks))

    def add_tracks(self, playlist_id: str, tracks: List[dict], smart: bool = True) -> dict:
        return self._run(self._async.add_tracks(playlist_id, tracks, smart))

    def smart_refresh(self, playlist_id: str, new_tracks: List[dict]) -> dict:
        return self._run(self._async.smart_refresh(playlist_id, new_tracks))

    def get_home(self) -> dict:
        return self._run(self._async.get_home())

    def get_blueprint(self) -> Optional[dict]:
        return self._run(self._async.get_blueprint())

    def get_profile(self) -> dict:
        return self._run(self._async.get_profile())

    def update_profile(self, **kwargs) -> dict:
        return self._run(self._async.update_profile(**kwargs))

    def onboarding_step1(self, languages: List[str]) -> dict:
        return self._run(self._async.onboarding_step1(languages))

    def onboarding_step2(self, artists: List[str]) -> dict:
        return self._run(self._async.onboarding_step2(artists))

    def close(self):
        self._run(self._async.close())


# Global instance for legacy app
api_client = SyncApiClient(os.getenv("API_BASE_URL", "http://localhost:8000/api/v1"))