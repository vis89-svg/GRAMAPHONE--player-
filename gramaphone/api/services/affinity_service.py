from typing import Optional
from sqlalchemy import select, func, and_, cast, Integer
from sqlalchemy.ext.asyncio import AsyncSession
from api.models import (
    ListeningHistory, ArtistAffinity, TasteProfile, 
    RecommendationHistory, PlaylistTrack, Playlist
)
from api.services.search_service import SearchService
import uuid
from datetime import datetime, timedelta


async def get_artist_affinity(
    db: AsyncSession, 
    profile_id: uuid.UUID, 
    artist_name: str
) -> Optional[ArtistAffinity]:
    result = await db.execute(
        select(ArtistAffinity).where(
            ArtistAffinity.profile_id == profile_id,
            ArtistAffinity.artist_name == artist_name
        )
    )
    return result.scalar_one_or_none()


async def recalculate_affinities(db: AsyncSession, profile_id: uuid.UUID) -> int:
    """Recalculate artist affinities with recency weighting."""
    # Recency weights
    # 7 days: 1.0, 30 days: 0.8, 90 days: 0.6, 365 days: 0.3, older: 0.1
    
    # Delete old
    await db.execute(
        ArtistAffinity.__table__.delete().where(ArtistAffinity.profile_id == profile_id)
    )

    # Aggregate with recency weighting
    result = await db.execute("""
        SELECT 
            artist,
            SUM(CASE 
                WHEN played_at >= NOW() - INTERVAL '7 days' THEN 1.0
                WHEN played_at >= NOW() - INTERVAL '30 days' THEN 0.8
                WHEN played_at >= NOW() - INTERVAL '90 days' THEN 0.6
                WHEN played_at >= NOW() - INTERVAL '365 days' THEN 0.3
                ELSE 0.1
            END) as weighted_plays,
            SUM(completed::int * CASE 
                WHEN played_at >= NOW() - INTERVAL '7 days' THEN 1.0
                WHEN played_at >= NOW() - INTERVAL '30 days' THEN 0.8
                WHEN played_at >= NOW() - INTERVAL '90 days' THEN 0.6
                WHEN played_at >= NOW() - INTERVAL '365 days' THEN 0.3
                ELSE 0.1
            END) as weighted_completed,
            SUM(skipped::int * CASE 
                WHEN played_at >= NOW() - INTERVAL '7 days' THEN 1.0
                WHEN played_at >= NOW() - INTERVAL '30 days' THEN 0.8
                WHEN played_at >= NOW() - INTERVAL '90 days' THEN 0.6
                WHEN played_at >= NOW() - INTERVAL '365 days' THEN 0.3
                ELSE 0.1
            END) as weighted_skipped,
            SUM(play_duration_sec * CASE 
                WHEN played_at >= NOW() - INTERVAL '7 days' THEN 1.0
                WHEN played_at >= NOW() - INTERVAL '30 days' THEN 0.8
                WHEN played_at >= NOW() - INTERVAL '90 days' THEN 0.6
                WHEN played_at >= NOW() - INTERVAL '365 days' THEN 0.3
                ELSE 0.1
            END) as weighted_duration
        FROM listening_history
        WHERE profile_id = :pid
        GROUP BY artist
    """, {"pid": profile_id})

    rows = result.all()
    
    # Get favorite counts from playlists
    fav_counts = {}
    if rows:
        artists = [r[0] for r in rows]
        fav_result = await db.execute(
            select(PlaylistTrack.artist, func.count())
            .where(
                PlaylistTrack.artist.in_(artists),
                PlaylistTrack.playlist_id.in_(
                    select(Playlist.id).where(Playlist.profile_id == profile_id)
                )
            )
            .group_by(PlaylistTrack.artist)
        )
        fav_counts = dict(fav_result.all())

    # Calculate scores and upsert
    for artist, plays, completed, skipped, duration in rows:
        fav = fav_counts.get(artist, 0)
        score = (
            (plays or 0) * 1.0 + 
            (completed or 0) * 2.0 - 
            (skipped or 0) * 0.5 + 
            fav * 3.0 + 
            min((duration or 0) / 60, 50)
        )
        score = max(0, score)

        affinity = ArtistAffinity(
            profile_id=profile_id,
            artist_name=artist,
            play_count=int(plays or 0),
            completed_count=int(completed or 0),
            skip_count=int(skipped or 0),
            fav_count=fav,
            affinity_score=score,
            last_updated=datetime.utcnow()
        )
        db.add(affinity)

    await db.flush()
    return len(rows)


async def recalculate_taste_profile(db: AsyncSession, profile_id: uuid.UUID) -> int:
    """Calculate genre percentages from listening history."""
    await db.execute(
        TasteProfile.__table__.delete().where(TasteProfile.profile_id == profile_id)
    )

    # Get artists from history
    result = await db.execute(
        select(ListeningHistory.artist).where(
            ListeningHistory.profile_id == profile_id
        ).distinct()
    )
    artists = [r[0] for r in result.all()]

    # Get genres via search service (cached)
    search = SearchService()
    genre_counts = {}
    total = 0

    for artist in artists:
        genre = await search.get_artist_genre(artist)
        if genre:
            genre_counts[genre] = genre_counts.get(genre, 0) + 1
            total += 1

    # Add favorite artists (2x weight)
    from api.dependencies.database import get_db
    # This would need profile fav_artists - skip for now

    if total > 0:
        for genre, count in sorted(genre_counts.items(), key=lambda x: -x[1]):
            pct = round(count / total * 100, 1)
            db.add(TasteProfile(
                profile_id=profile_id,
                genre=genre,
                percentage=pct,
                last_updated=datetime.utcnow()
            ))

    await db.flush()
    return len(genre_counts)


async def get_top_affinity_artists(
    db: AsyncSession, 
    profile_id: uuid.UUID, 
    limit: int = 10
) -> list[dict]:
    result = await db.execute(
        select(ArtistAffinity.artist_name, ArtistAffinity.affinity_score)
        .where(ArtistAffinity.profile_id == profile_id)
        .order_by(ArtistAffinity.affinity_score.desc())
        .limit(limit)
    )
    return [{"artist_name": r[0], "affinity_score": r[1]} for r in result.all()]


async def get_taste_profile(
    db: AsyncSession, 
    profile_id: uuid.UUID, 
    limit: int = 5
) -> list[dict]:
    result = await db.execute(
        select(TasteProfile.genre, TasteProfile.percentage)
        .where(TasteProfile.profile_id == profile_id)
        .order_by(TasteProfile.percentage.desc())
        .limit(limit)
    )
    return [{"genre": r[0], "percentage": r[1]} for r in result.all()]


async def get_recent_plays(
    db: AsyncSession, 
    profile_id: uuid.UUID, 
    limit: int = 50,
    days: int = 7
) -> list[dict]:
    result = await db.execute(
        select(
            ListeningHistory.title,
            ListeningHistory.artist,
            ListeningHistory.album,
            ListeningHistory.completed,
            ListeningHistory.skipped,
            ListeningHistory.play_duration_sec,
            ListeningHistory.track_duration_sec
        )
        .where(
            ListeningHistory.profile_id == profile_id,
            ListeningHistory.played_at >= datetime.utcnow() - timedelta(days=days)
        )
        .order_by(ListeningHistory.played_at.desc())
        .limit(limit)
    )
    return [
        {
            "title": r[0],
            "artist": r[1],
            "album": r[2],
            "completed": r[3],
            "skipped": r[4],
            "play_duration_sec": r[5],
            "track_duration_sec": r[6]
        }
        for r in result.all()
    ]


async def get_completion_stats(db: AsyncSession, profile_id: uuid.UUID) -> tuple[float, float]:
    """Get completion rate and skip rate."""
    result = await db.execute(
        select(
            func.count().label("total"),
            func.sum(cast(ListeningHistory.completed, Integer)).label("completed"),
            func.sum(cast(ListeningHistory.skipped, Integer)).label("skipped")
        ).where(
            ListeningHistory.profile_id == profile_id,
            ListeningHistory.played_at >= datetime.utcnow() - timedelta(days=7)
        )
    )
    row = result.one()
    total = row.total or 1
    completed = row.completed or 0
    skipped = row.skipped or 0
    return (completed / total * 100, skipped / total * 100)


async def get_tod_genres(db: AsyncSession, profile_id: uuid.UUID) -> list[dict]:
    """Get genres preferred at different times of day."""
    hour = datetime.now().hour
    if hour < 12:
        period = "morning"
        start_h, end_h = 6, 12
    elif hour < 17:
        period = "afternoon"
        start_h, end_h = 12, 17
    elif hour < 21:
        period = "evening"
        start_h, end_h = 17, 21
    else:
        period = "night"
        start_h, end_h = 21, 6

    # This is simplified - real impl would query by hour of played_at
    result = await db.execute(
        select(ListeningHistory.artist)
        .where(
            ListeningHistory.profile_id == profile_id,
            # Hour filtering would go here
        )
        .distinct()
        .limit(15)
    )
    artists = [r[0] for r in result.all()]

    search = SearchService()
    genres = []
    for artist in artists:
        genre = await search.get_artist_genre(artist)
        if genre:
            genres.append(genre)

    if not genres:
        return []

    # Most common genre for current period
    from collections import Counter
    genre_counts = Counter(genres)
    top_genre = genre_counts.most_common(1)[0][0]
    return [{"period": period, "genres": [top_genre]}]


async def get_active_playlists(db: AsyncSession, profile_id: uuid.UUID, days: int = 14) -> list[str]:
    """Get playlist names visited in recent days."""
    # This would need a playlist_visits table - placeholder
    return []


async def get_listening_streak(db: AsyncSession, profile_id: uuid.UUID) -> int:
    """Calculate consecutive days of listening."""
    # Simplified - real impl would check each day
    result = await db.execute(
        select(func.count(func.distinct(func.date(ListeningHistory.played_at))))
        .where(ListeningHistory.profile_id == profile_id)
    )
    return result.scalar() or 0


async def get_collaborative_recommendations(
    db: AsyncSession, 
    profile_id: uuid.UUID, 
    limit: int = 5
) -> list[dict]:
    """Jaccard similarity with other users."""
    # Get my songs
    my_songs_result = await db.execute(
        select(ListeningHistory.title, ListeningHistory.artist)
        .where(ListeningHistory.profile_id == profile_id)
        .distinct()
    )
    my_set = set(f"{t}||{a}" for t, a in my_songs_result.all())

    if len(my_set) < 5:
        return []

    # Get other users
    other_users = await db.execute(
        select(ListeningHistory.profile_id)
        .where(ListeningHistory.profile_id != profile_id)
        .distinct()
    )
    
    recommendations = []
    for (uid,) in other_users.all()[:20]:  # Check up to 20 users
        their_songs = await db.execute(
            select(ListeningHistory.title, ListeningHistory.artist)
            .where(ListeningHistory.profile_id == uid)
            .distinct()
        )
        their_set = set(f"{t}||{a}" for t, a in their_songs.all())
        
        if not their_set:
            continue
            
        intersection = len(my_set & their_set)
        union = len(my_set | their_set)
        jaccard = intersection / union if union > 0 else 0
        
        if jaccard > 0.1:
            for song in (their_set - my_set):
                parts = song.split("||")
                recommendations.append({"title": parts[0], "artist": parts[1]})
                if len(recommendations) >= limit:
                    return recommendations
    
    return recommendations


async def is_recently_recommended(
    db: AsyncSession,
    profile_id: uuid.UUID,
    rec_type: str,
    item_key: str,
    days: int = 1
) -> bool:
    """Check if item was recently recommended (avoid repeats)."""
    result = await db.execute(
        select(RecommendationHistory.id).where(
            RecommendationHistory.profile_id == profile_id,
            RecommendationHistory.rec_type == rec_type,
            RecommendationHistory.item_key == item_key,
            RecommendationHistory.recommended_at >= datetime.utcnow() - timedelta(days=days)
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def log_recommendation(
    db: AsyncSession,
    profile_id: uuid.UUID,
    rec_type: str,
    item_key: str,
    item_name: str
):
    db.add(RecommendationHistory(
        profile_id=profile_id,
        rec_type=rec_type,
        item_key=item_key,
        item_name=item_name
    ))
    await db.flush()