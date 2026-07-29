import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from api.dependencies.database import get_db
from api.services.search_service import SearchService, pick_best_yt_version
from api.schemas.search import (
    SearchResult, Track, Album, Artist, Playlist,
    AlbumTracksResponse, YouTubeSearchResult, YouTubeVersion,
    SearchSuggestionsResponse, SearchQuery
)

router = APIRouter(prefix="/search", tags=["search"])


_search_service: SearchService = None


def get_search_service() -> SearchService:
    global _search_service
    if _search_service is None:
        _search_service = SearchService()
    return _search_service


@router.get("", response_model=SearchResult)
async def search_all(
    q: str = Query(..., min_length=1, max_length=200),
    type: str = Query("all", pattern="^(all|track|album|artist|playlist)$"),
    limit: int = Query(20, ge=1, le=100),
    service: SearchService = Depends(get_search_service),
):
    """Unified search endpoint."""
    if type == "all":
        results = await service.search_all(q, limit)
    elif type == "track":
        tracks = await service.search_tracks(q, limit)
        results = {"tracks": tracks, "albums": [], "artists": [], "playlists": []}
    elif type == "album":
        albums = await service.search_albums(q, limit)
        results = {"tracks": [], "albums": albums, "artists": [], "playlists": []}
    elif type == "artist":
        artists = await service.search_artists(q, limit)
        results = {"tracks": [], "albums": [], "artists": artists, "playlists": []}
    elif type == "playlist":
        playlists = await service.search_playlists(q, limit)
        results = {"tracks": [], "albums": [], "artists": [], "playlists": playlists}
    else:
        raise HTTPException(400, "Invalid search type")

    return SearchResult(
        tracks=[Track.model_validate(t.__dict__) for t in results.get("tracks", [])],
        albums=[Album.model_validate(a.__dict__) for a in results.get("albums", [])],
        artists=[Artist.model_validate(a.__dict__) for a in results.get("artists", [])],
        playlists=[Playlist.model_validate(p.__dict__) for p in results.get("playlists", [])],
    )


@router.get("/album/{album_id}/tracks", response_model=AlbumTracksResponse)
async def get_album_tracks(
    album_id: str,
    service: SearchService = Depends(get_search_service),
):
    """Get ONLY tracks from a specific album (no live/cover duplicates from other albums)."""
    album = await service.get_album_by_id(album_id)
    if not album:
        raise HTTPException(404, "Album not found")
    tracks = await service.get_album_tracks(album_id)
    return AlbumTracksResponse(
        album=Album.model_validate(album.__dict__),
        tracks=[Track.model_validate(t.__dict__) for t in tracks]
    )


@router.get("/artist/{artist_id}/albums")
async def get_artist_albums(
    artist_id: str,
    limit: int = Query(20, ge=1, le=50),
    service: SearchService = Depends(get_search_service),
):
    albums = await service.get_artist_albums(artist_id, limit)
    return [Album.model_validate(a.__dict__) for a in albums]


@router.get("/artist/{artist_id}/tracks")
async def get_artist_tracks(
    artist_id: str,
    limit: int = Query(20, ge=1, le=50),
    service: SearchService = Depends(get_search_service),
):
    tracks = await service.get_artist_top_tracks(artist_id, limit)
    return [Track.model_validate(t.__dict__) for t in tracks]


@router.get("/suggestions", response_model=SearchSuggestionsResponse)
async def get_suggestions(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=20),
    service: SearchService = Depends(get_search_service),
):
    suggestions = await service.get_suggestions(q, limit)
    return SearchSuggestionsResponse(suggestions=suggestions)


# ===== YOUTUBE VERSION SELECTION =====

@router.get("/youtube/versions", response_model=YouTubeSearchResult)
async def get_youtube_versions(
    artist: str = Query(..., min_length=1),
    title: str = Query(..., min_length=1),
    album: str = Query("", max_length=200),
    duration_ms: int = Query(0, ge=0),
):
    """Get YouTube versions ranked by quality (Topic > lyrics > audio > official)."""
    from yt_dlp import YoutubeDL
    
    queries = [
        f"{artist} {title} Topic",
        f"{artist} {title} lyrics",
        f"{artist} {title} audio",
        f"{artist} {title} official audio",
        f"{artist} {title} {album} official audio" if album else "",
        f"{artist} {title}",
    ]
    queries = [q for q in queries if q]

    all_results = []
    ydl_opts = {
        "quiet": True,
        "extract_flat": "in_playlist",
        "dumpjson": True,
        "skip_download": True,
    }

    for query in queries[:4]:  # Limit to first 4 queries to save time
        try:
            with YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(f"ytsearch5:{query}", download=False)
                if result and "entries" in result:
                    for entry in result["entries"]:
                        if entry and entry.get("id"):
                            all_results.append({
                                "video_id": entry["id"],
                                "title": entry.get("title", ""),
                                "channel": entry.get("channel", entry.get("uploader", "")),
                                "duration": entry.get("duration", 0),
                                "thumbnail": entry.get("thumbnail", ""),
                            })
        except Exception:
            continue

    # Deduplicate by video_id
    seen = set()
    unique = []
    for r in all_results:
        if r["video_id"] not in seen:
            seen.add(r["video_id"])
            unique.append(r)

    # Score and pick best
    best_raw = pick_best_yt_version(unique, duration_ms // 1000)
    versions = [
        YouTubeVersion(
            video_id=r["video_id"],
            title=r["title"],
            channel=r["channel"],
            duration=r["duration"],
            artwork_url=r["thumbnail"],
        )
        for r in unique
    ]
    best_version = None
    if best_raw:
        best_version = YouTubeVersion(
            video_id=best_raw["video_id"],
            title=best_raw["title"],
            channel=best_raw["channel"],
            duration=best_raw["duration"],
            artwork_url=best_raw["thumbnail"],
        )

    return YouTubeSearchResult(versions=versions, best_version=best_version)