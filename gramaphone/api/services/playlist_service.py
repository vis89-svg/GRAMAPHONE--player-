import uuid
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from api.models import Playlist, PlaylistTrack, ListeningHistory, ArtistAffinity
from api.services.search_service import SearchService


async def create_playlist(
    db: AsyncSession,
    profile_id: uuid.UUID,
    name: str,
    source: str = "user",
    tracks: list[dict] = None
) -> Playlist:
    """Create a new playlist with optional tracks."""
    playlist = Playlist(
        profile_id=profile_id,
        name=name,
        source=source
    )
    db.add(playlist)
    await db.flush()

    if tracks:
        for i, track in enumerate(tracks):
            db.add(PlaylistTrack(
                playlist_id=playlist.id,
                track_id=track.get("track_id"),
                title=track.get("title", ""),
                artist=track.get("artist", ""),
                album=track.get("album"),
                art_url=track.get("artwork_url"),
                position=i
            ))

    await db.flush()
    return playlist


async def get_playlist(db: AsyncSession, playlist_id: uuid.UUID, profile_id: uuid.UUID) -> Optional[Playlist]:
    """Get a single playlist by ID."""
    result = await db.execute(
        select(Playlist).where(
            Playlist.id == playlist_id,
            Playlist.profile_id == profile_id
        )
    )
    return result.scalar_one_or_none()


async def get_user_playlists(db: AsyncSession, profile_id: uuid.UUID) -> list[Playlist]:
    """Get all playlists for a user."""
    result = await db.execute(
        select(Playlist)
        .where(Playlist.profile_id == profile_id)
        .order_by(Playlist.created_at.desc())
    )
    return result.scalars().all()


async def add_tracks_to_playlist(
    db: AsyncSession,
    playlist_id: uuid.UUID,
    tracks: list[dict],
) -> int:
    """Add tracks to a playlist, return count added."""
    result = await db.execute(
        select(func.max(PlaylistTrack.position)).where(PlaylistTrack.playlist_id == playlist_id)
    )
    pos = (result.scalar() or 0) + 1
    for track in tracks:
        db.add(PlaylistTrack(
            playlist_id=playlist_id,
            track_id=track.get("track_id", ""),
            title=track.get("title", ""),
            artist=track.get("artist", ""),
            album=track.get("album"),
            art_url=track.get("artwork_url"),
            position=pos
        ))
        pos += 1
    await db.flush()
    return len(tracks)


async def delete_playlist(db: AsyncSession, playlist_id: uuid.UUID, profile_id: uuid.UUID) -> bool:
    """Delete a playlist and its tracks."""
    async with db.begin():
        await db.execute(
            delete(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
        )
        result = await db.execute(
            delete(Playlist).where(
                Playlist.id == playlist_id,
                Playlist.profile_id == profile_id
            )
        )
    return result.rowcount > 0


async def smart_merge_playlist(
    db: AsyncSession,
    playlist_id: uuid.UUID,
    new_tracks: list[dict],
    max_size: int = 50,
    keep_threshold: float = 0.7
) -> dict:
    """
    Smart merge: keep loved tracks, replace stale ones.
    
    Keep criteria:
    - affinity_score > keep_threshold * max_affinity
    - completed > 2 times
    - manually added (position < 1000 heuristic)
    Replace: oldest skipped, lowest affinity
    """
    # Get current tracks
    current_result = await db.execute(
        select(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
        .order_by(PlaylistTrack.position)
    )
    current_tracks = list(current_result.scalars().all())
    
    if not current_tracks:
        # Empty playlist - just add all
        for i, track in enumerate(new_tracks[:max_size]):
            db.add(PlaylistTrack(
                playlist_id=playlist_id,
                track_id=track.get("track_id"),
                title=track.get("title", ""),
                artist=track.get("artist", ""),
                album=track.get("album"),
                art_url=track.get("artwork_url"),
                position=i
            ))
        return {"added": len(new_tracks), "kept": 0, "removed": 0}

    # Get profile_id from playlist
    playlist_result = await db.execute(
        select(Playlist.profile_id).where(Playlist.id == playlist_id)
    )
    profile_id = playlist_result.scalar_one()

    # Get affinity scores for current track artists
    current_artists = list(set(t.artist for t in current_tracks))
    affinity_result = await db.execute(
        select(ArtistAffinity.artist_name, ArtistAffinity.affinity_score)
        .where(
            ArtistAffinity.profile_id == profile_id,
            ArtistAffinity.artist_name.in_(current_artists)
        )
    )
    affinity_map = dict(affinity_result.all())
    max_affinity = max(affinity_map.values()) if affinity_map else 1.0

    # Get play stats for current tracks
    track_keys = [(t.title, t.artist) for t in current_tracks]
    stats_result = await db.execute("""
        SELECT title, artist,
               COUNT(*) as plays,
               SUM(completed::int) as completed,
               SUM(skipped::int) as skipped,
               MAX(played_at) as last_played
        FROM listening_history
        WHERE profile_id = :pid AND (title, artist) IN :keys
        GROUP BY title, artist
    """, {"pid": profile_id, "keys": tuple(track_keys)})
    
    stats_map = {}
    for row in stats_result.all():
        stats_map[(row.title, row.artist)] = {
            "plays": row.plays,
            "completed": row.completed,
            "skipped": row.skipped,
            "last_played": row.last_played
        }

    # Score each current track
    scored_tracks = []
    for track in current_tracks:
        key = (track.title, track.artist)
        stats = stats_map.get(key, {})
        affinity = affinity_map.get(track.artist, 0)
        
        # Keep score: high affinity + high completion + recent plays
        keep_score = (
            (affinity / max_affinity) * 0.4 +
            (min(stats.get("completed", 0), 5) / 5) * 0.3 +
            (1 if stats.get("last_played") and 
             stats["last_played"] > datetime.utcnow() - timedelta(days=14) else 0) * 0.3
        )
        
        scored_tracks.append({
            "track": track,
            "keep_score": keep_score,
            "stats": stats,
            "affinity": affinity
        })

    # Sort by keep score descending
    scored_tracks.sort(key=lambda x: -x["keep_score"])

    # Determine keep vs replace
    keep_count = max(1, int(len(scored_tracks) * keep_threshold))
    to_keep = scored_tracks[:keep_count]
    to_replace = scored_tracks[keep_count:]

    # Build new track list: kept tracks first (preserve order), then new tracks
    final_tracks = []
    
    # Re-position kept tracks
    for i, item in enumerate(to_keep):
        t = item["track"]
        t.position = i
        final_tracks.append(t)

    # Add new tracks
    new_track_objs = []
    for i, new_track in enumerate(new_tracks):
        if len(final_tracks) >= max_size:
            break
        pos = len(final_tracks)
        track_obj = PlaylistTrack(
            playlist_id=playlist_id,
            track_id=new_track.get("track_id"),
            title=new_track.get("title", ""),
            artist=new_track.get("artist", ""),
            album=new_track.get("album"),
            art_url=new_track.get("artwork_url"),
            position=pos
        )
        new_track_objs.append(track_obj)
        final_tracks.append(track_obj)

    # Delete replaced tracks
    replace_ids = [item["track"].id for item in to_replace]
    if replace_ids:
        await db.execute(
            delete(PlaylistTrack).where(PlaylistTrack.id.in_(replace_ids))
        )

    # Add new tracks
    db.add_all(new_track_objs)

    await db.flush()

    return {
        "kept": len(to_keep),
        "added": len(new_track_objs),
        "removed": len(to_replace),
        "total": len(final_tracks)
    }


async def refresh_auto_playlist(
    db: AsyncSession,
    profile_id: uuid.UUID,
    playlist_name: str,
    new_tracks: list[dict],
    source: str,
    max_size: int = 50
) -> dict:
    """Refresh or create an auto-generated playlist."""
    # Find existing
    result = await db.execute(
        select(Playlist).where(
            Playlist.profile_id == profile_id,
            Playlist.name == playlist_name,
            Playlist.source == source
        )
    )
    playlist = result.scalar_one_or_none()

    if playlist:
        return await smart_merge_playlist(db, playlist.id, new_tracks, max_size)
    else:
        playlist = await create_playlist(db, profile_id, playlist_name, source, new_tracks[:max_size])
        return {"kept": 0, "added": len(playlist.tracks), "removed": 0, "total": len(playlist.tracks)}


# ===== AUTO PLAYLIST GENERATORS =====

async def generate_forgotten_favorites(
    db: AsyncSession,
    profile_id: uuid.UUID
) -> list[dict]:
    """Songs played 3+ times but not in last 14 days."""
    result = await db.execute("""
        SELECT title, artist, album, art_url, COUNT(*) as cnt
        FROM listening_history
        WHERE profile_id = :pid
          AND played_at < NOW() - INTERVAL '14 days'
        GROUP BY title, artist, album, art_url
        HAVING COUNT(*) >= 3
        ORDER BY cnt DESC
        LIMIT 15
    """, {"pid": profile_id})
    
    tracks = []
    for row in result.all():
        tracks.append({
            "title": row.title,
            "artist": row.artist,
            "album": row.album,
            "artwork_url": row.art_url,
        })
    return tracks


async def generate_recently_loved(
    db: AsyncSession,
    profile_id: uuid.UUID
) -> list[dict]:
    """High completion rate songs from last 30 days."""
    result = await db.execute("""
        SELECT title, artist, album, art_url, COUNT(*) as cnt
        FROM listening_history
        WHERE profile_id = :pid
          AND completed = true
          AND played_at > NOW() - INTERVAL '30 days'
        GROUP BY title, artist, album, art_url
        ORDER BY cnt DESC
        LIMIT 15
    """, {"pid": profile_id})
    
    return [{
        "title": r.title, "artist": r.artist, 
        "album": r.album, "artwork_url": r.art_url
    } for r in result.all()]


async def generate_daily_mix(
    db: AsyncSession,
    profile_id: uuid.UUID,
    blueprint: dict
) -> list[dict]:
    """Generate Daily Mix from blueprint seed tracks + genre/artist expansions."""
    search = SearchService()
    tracks = []
    seen = set()

    # Add blueprint seed tracks first
    for seed in blueprint.get("seed_tracks", [])[:10]:
        key = f"{seed.get('title')}||{seed.get('artist')}"
        if key not in seen:
            seen.add(key)
            tracks.append(seed)

    # Expand from focus genres
    for genre in blueprint.get("strategy", {}).get("focus_genres", [])[:2]:
        genre_tracks = await search.search_tracks(genre, limit=8)
        for t in genre_tracks:
            key = f"{t.title}||{t.artist}"
            if key not in seen and len(tracks) < 20:
                seen.add(key)
                tracks.append({
                    "track_id": t.track_id,
                    "title": t.title,
                    "artist": t.artist,
                    "album": t.album,
                    "artwork_url": t.artwork_url,
                })

    # Expand from top affinity artists
    top_artists = blueprint.get("strategy", {}).get("top_artists", [])
    for artist in top_artists[:3]:
        artist_tracks = await search.search_tracks(artist, limit=5)
        for t in artist_tracks:
            key = f"{t.title}||{t.artist}"
            if key not in seen and len(tracks) < 25:
                seen.add(key)
                tracks.append({
                    "track_id": t.track_id,
                    "title": t.title,
                    "artist": t.artist,
                    "album": t.album,
                    "artwork_url": t.artwork_url,
                })

    return tracks[:25]


async def generate_hidden_gems(
    db: AsyncSession,
    profile_id: uuid.UUID
) -> list[dict]:
    """Deep cuts from top affinity artists (less popular tracks)."""
    search = SearchService()
    
    # Get top affinity artists
    affinity_result = await db.execute(
        select(ArtistAffinity.artist_name)
        .where(ArtistAffinity.profile_id == profile_id)
        .order_by(ArtistAffinity.affinity_score.desc())
        .limit(2)
    )
    top_artists = [r[0] for r in affinity_result.all()]
    
    gems = []
    for artist in top_artists:
        tracks = await search.get_artist_top_tracks(artist, limit=15)
        # Sort by duration (shorter = potentially less known) or just take later tracks
        for t in tracks[5:10]:  # Skip top 5
            gems.append({
                "track_id": t.track_id,
                "title": t.title,
                "artist": t.artist,
                "album": t.album,
                "artwork_url": t.artwork_url,
            })
            if len(gems) >= 15:
                break
    
    return gems


async def run_nightly_playlist_refresh(db: AsyncSession):
    """Main entry point for nightly cron job."""
    # Get all profiles with recent activity
    profiles_result = await db.execute(
        select(Playlist.profile_id)
        .where(Playlist.source.like('auto_%'))
        .distinct()
    )
    profile_ids = [r[0] for r in profiles_result.all()]

    for profile_id in profile_ids:
        try:
            # Get today's blueprint
            from api.services.blueprint_service import blueprint_service
            blueprint = await blueprint_service.generate_blueprint(db, profile_id)
            
            bp_data = {
                "seed_tracks": blueprint.seed_tracks,
                "strategy": blueprint.strategy,
            }

            # Refresh each auto playlist
            await refresh_auto_playlist(
                db, profile_id, "Daily Mix", 
                await generate_daily_mix(db, profile_id, bp_data), 
                "auto_daily"
            )
            
            await refresh_auto_playlist(
                db, profile_id, "Forgotten Favorites",
                await generate_forgotten_favorites(db, profile_id),
                "auto_forgotten"
            )

            await refresh_auto_playlist(
                db, profile_id, "Recently Loved",
                await generate_recently_loved(db, profile_id),
                "auto_loved"
            )

            await refresh_auto_playlist(
                db, profile_id, "Hidden Gems",
                await generate_hidden_gems(db, profile_id),
                "auto_gems"
            )

            await db.commit()
        except Exception as e:
            print(f"Nightly refresh failed for {profile_id}: {e}")
            await db.rollback()