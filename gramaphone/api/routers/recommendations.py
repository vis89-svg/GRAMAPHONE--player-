from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
import uuid

from api.dependencies.database import get_db
from api.dependencies.auth import get_current_profile
from api.models import Profile, ListeningHistory, ArtistAffinity, TasteProfile, DailyBlueprint, RecommendationHistory
from api.services.search_service import SearchService
from api.services.affinity_service import (
    get_top_affinity_artists, get_taste_profile, get_recent_plays,
    get_completion_stats, get_tod_genres, get_active_playlists,
    get_listening_streak, get_collaborative_recommendations,
    is_recently_recommended, log_recommendation
)
from api.services.blueprint_service import get_today_blueprint

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/home")
async def get_home(
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    """Get home page data: mixes, suggestions, recently played, blueprint."""
    # Get today's blueprint
    blueprint = await get_today_blueprint(profile.id, db)
    
    # Get auto playlists (mixes)
    from api.models import Playlist
    result = await db.execute(
        select(Playlist).where(
            Playlist.profile_id == profile.id,
            Playlist.source.like("auto_%")
        ).order_by(Playlist.created_at.desc())
    )
    auto_playlists = result.scalars().all()
    
    mixes = [
        {
            "id": str(p.id),
            "name": p.name,
            "source": p.source,
            "track_count": len(p.tracks),
            "artwork_url": p.tracks[0].art_url if p.tracks else None
        }
        for p in auto_playlists
    ]
    
    # Suggested artists (from blueprint seed tracks)
    suggested_artists = []
    if blueprint:
        seen = set()
        for seed in blueprint.seed_tracks[:10]:
            artist = seed.get("artist", "")
            if artist and artist not in seen:
                seen.add(artist)
                suggested_artists.append({"artist": artist, "reason": seed.get("reason", "")})
    
    # Recently played
    recent_result = await db.execute(
        select(ListeningHistory)
        .where(ListeningHistory.profile_id == profile.id)
        .order_by(ListeningHistory.played_at.desc())
        .limit(10)
    )
    recently_played = [
        {
            "title": h.title,
            "artist": h.artist,
            "album": h.album,
            "artwork_url": h.art_url,
            "played_at": h.played_at
        }
        for h in recent_result.scalars().all()
    ]
    
    # Trending (top genres from all users - simplified)
    genre_result = await db.execute(
        select(TasteProfile.genre, func.sum(TasteProfile.percentage).label("total"))
        .group_by(TasteProfile.genre)
        .order_by(func.sum(TasteProfile.percentage).desc())
        .limit(5)
    )
    trending_genres = [{"genre": r[0], "score": round(r[1], 1)} for r in genre_result.all()]
    
    return {
        "mixes": mixes,
        "suggested_artists": suggested_artists,
        "recently_played": recently_played,
        "trending_genres": trending_genres,
        "blueprint": blueprint.strategy if blueprint else None
    }


@router.get("/artists")
async def get_suggested_artists(
    limit: int = Query(20, le=50),
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    """Get suggested artists based on taste profile + collaborative filtering."""
    top_artists = await get_top_affinity_artists(db, profile.id, 10)
    collab = await get_collaborative_recommendations(db, profile.id, 5)
    tod = await get_tod_genres(db, profile.id)
    
    search = SearchService()
    suggestions = []
    seen = set()
    
    # From top affinity artists -> get similar
    for artist_data in top_artists[:5]:
        artist = artist_data["artist_name"]
        try:
            similar = await search.search_artists(artist, limit=5)
            for s in similar:
                if s.name not in seen and s.name != artist:
                    seen.add(s.name)
                    suggestions.append({
                        "artist": s.name,
                        "genre": s.genre,
                        "artwork_url": s.artwork_url,
                        "reason": f"Similar to {artist}"
                    })
        except Exception:
            pass
    
    # From collaborative filtering
    for rec in collab:
        if rec["artist"] not in seen:
            seen.add(rec["artist"])
            suggestions.append({
                "artist": rec["artist"],
                "reason": "Listeners like you also play this"
            })
    
    # From time-of-day genres
    for tod_item in tod:
        for genre in tod_item.get("genres", []):
            try:
                genre_artists = await search.search_artists(genre, limit=3)
                for ga in genre_artists:
                    if ga.name not in seen:
                        seen.add(ga.name)
                        suggestions.append({
                            "artist": ga.name,
                            "genre": ga.genre,
                            "artwork_url": ga.artwork_url,
                            "reason": f"Popular in {tod_item['period']} ({genre})"
                        })
            except Exception:
                pass
    
    # Avoid recently recommended
    filtered = []
    for s in suggestions:
        if not await is_recently_recommended(db, profile.id, "artist", s["artist"]):
            filtered.append(s)
            if len(filtered) >= limit:
                break
    
    # Log recommendations
    for s in filtered:
        await log_recommendation(db, profile.id, "artist", s["artist"], s["artist"])
    
    await db.commit()
    return {"artists": filtered}


@router.get("/albums")
async def get_suggested_albums(
    limit: int = Query(20, le=50),
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    """Get suggested albums from top artists + genres."""
    top_artists = await get_top_affinity_artists(db, profile.id, 5)
    top_genres = await get_taste_profile(db, profile.id, 3)
    
    search = SearchService()
    suggestions = []
    seen = set()
    
    # Albums from top artists
    for artist_data in top_artists:
        artist = artist_data["artist_name"]
        try:
            albums = await search.get_artist_albums(artist, limit=5)
            for a in albums:
                key = f"{a.title}||{a.artist}"
                if key not in seen:
                    seen.add(key)
                    suggestions.append({
                        "album_id": a.album_id,
                        "title": a.title,
                        "artist": a.artist,
                        "artwork_url": a.artwork_url,
                        "release_date": a.release_date,
                        "track_count": a.track_count,
                        "reason": f"From {artist} (affinity: {artist_data['affinity_score']:.0f})"
                    })
        except Exception:
            pass
    
    # Albums from top genres
    for genre_data in top_genres:
        try:
            genre_albums = await search.search_albums(genre_data["genre"], limit=5)
            for a in genre_albums:
                key = f"{a.title}||{a.artist}"
                if key not in seen:
                    seen.add(key)
                    suggestions.append({
                        "album_id": a.album_id,
                        "title": a.title,
                        "artist": a.artist,
                        "artwork_url": a.artwork_url,
                        "release_date": a.release_date,
                        "track_count": a.track_count,
                        "reason": f"Top genre: {genre_data['genre']} ({genre_data['percentage']:.1f}%)"
                    })
        except Exception:
            pass
    
    # Filter recently recommended
    filtered = []
    for s in suggestions:
        if not await is_recently_recommended(db, profile.id, "album", s["title"] + "||" + s["artist"]):
            filtered.append(s)
            if len(filtered) >= limit:
                break
    
    for s in filtered:
        await log_recommendation(db, profile.id, "album", s["title"] + "||" + s["artist"], s["title"])
    
    await db.commit()
    return {"albums": filtered}


@router.get("/tracks")
async def get_suggested_tracks(
    limit: int = Query(30, le=100),
    slot: Optional[str] = Query(None, description="Filter by blueprint slot"),
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    """Get suggested tracks from blueprint + collaborative filtering."""
    blueprint = await get_today_blueprint(profile.id, db)
    top_artists = await get_top_affinity_artists(db, profile.id, 8)
    collab = await get_collaborative_recommendations(db, profile.id, 5)
    
    search = SearchService()
    suggestions = []
    seen = set()
    
    # From blueprint seed tracks
    if blueprint:
        for seed in blueprint.seed_tracks:
            if slot and seed.get("slot") != slot:
                continue
            key = f"{seed.get('track')}||{seed.get('artist')}"
            if key not in seen:
                seen.add(key)
                suggestions.append({
                    "track_id": seed.get("track_id"),
                    "title": seed.get("track"),
                    "artist": seed.get("artist"),
                    "album": seed.get("album"),
                    "artwork_url": seed.get("artwork_url"),
                    "slot": seed.get("slot"),
                    "reason": seed.get("reason")
                })
    
    # From collaborative filtering
    for rec in collab:
        key = f"{rec['track']}||{rec['artist']}"
        if key not in seen:
            seen.add(key)
            suggestions.append({
                "title": rec["track"],
                "artist": rec["artist"],
                "reason": "Listeners like you also play this"
            })
    
    # From top artists (top tracks)
    for artist_data in top_artists[:3]:
        try:
            tracks = await search.get_artist_top_tracks(artist_data["artist_name"], limit=5)
            for t in tracks:
                key = f"{t.title}||{t.artist}"
                if key not in seen:
                    seen.add(key)
                    suggestions.append({
                        "track_id": t.track_id,
                        "title": t.title,
                        "artist": t.artist,
                        "album": t.album,
                        "artwork_url": t.artwork_url,
                        "reason": f"Top track by {artist_data['artist_name']}"
                    })
        except Exception:
            pass
    
    # Filter recently recommended
    filtered = []
    for s in suggestions:
        if not await is_recently_recommended(db, profile.id, "song", s["title"] + "||" + s["artist"]):
            filtered.append(s)
            if len(filtered) >= limit:
                break
    
    for s in filtered:
        await log_recommendation(db, profile.id, "song", s["title"] + "||" + s["artist"], s["title"])
    
    await db.commit()
    return {"tracks": filtered}


@router.get("/related")
async def get_related_tracks(
    artist: str = Query(...),
    title: str = Query(...),
    duration_ms: int = Query(0),
    limit: int = Query(15, le=30),
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    """Get related tracks for autoplay. Uses YouTube related videos + iTunes fallback."""
    search = SearchService()
    tracks = await search.get_related_tracks(artist, title, duration_ms)

    # Deduplicate and limit
    seen = set()
    deduped = []
    for t in tracks:
        key = f"{t['title']}||{t['artist']}"
        if key not in seen:
            seen.add(key)
            deduped.append(t)
            if len(deduped) >= limit:
                break

    return {"tracks": deduped, "seed": {"artist": artist, "title": title}}


@router.get("/blueprint/today")
async def get_today_blueprint_endpoint(
    profile: Profile = Depends(get_current_profile),
    db: AsyncSession = Depends(get_db)
):
    blueprint = await get_today_blueprint(profile.id, db)
    if not blueprint:
        return {"message": "No blueprint generated yet"}
    return {
        "id": str(blueprint.id),
        "date": blueprint.date.isoformat(),
        "strategy": blueprint.strategy,
        "seed_tracks": blueprint.seed_tracks,
        "playlist_updates": blueprint.playlist_updates,
        "runtime_stats": blueprint.runtime_stats
    }