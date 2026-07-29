import json
import uuid
from datetime import date, datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI
import instructor
from pydantic import BaseModel, Field

from api.models import DailyBlueprint, Profile
from api.services.affinity_service import (
    get_top_affinity_artists, get_taste_profile, get_recent_plays,
    get_completion_stats, get_tod_genres, get_active_playlists,
    get_listening_streak, get_collaborative_recommendations,
    is_recently_recommended, log_recommendation
)
from api.services.search_service import SearchService
from api.services.quota_service import quota_service
from api.config import settings


# ===== STRUCTURED OUTPUT SCHEMAS =====

class SeedTrack(BaseModel):
    track: str
    artist: str
    slot: str = Field(description="morning_anchor, focus, discovery, wind_down, energy_boost, etc.")
    reason: str


class PlaylistUpdate(BaseModel):
    add: int = 0
    remove_stale: int = 0
    create_new: Optional[str] = None


class BlueprintStrategy(BaseModel):
    mood_arc: list[str] = Field(min_items=3, max_items=4)
    focus_genres: list[str] = Field(min_items=2, max_items=3)
    discovery_ratio: float = Field(ge=0.1, le=0.3)
    repeat_comfort_ratio: float = Field(ge=0.2, le=0.4)
    new_artist_exploration: list[str] = Field(min_items=2, max_items=3)


class BlueprintResponse(BaseModel):
    strategy: BlueprintStrategy
    seed_tracks: list[SeedTrack] = Field(min_items=15, max_items=20)
    playlist_updates: dict[str, PlaylistUpdate] = {}


# ===== PROMPT TEMPLATE =====

SYSTEM_PROMPT = """You are a music curation AI. Generate a daily listening blueprint as structured JSON.

Rules:
- Output ONLY valid JSON matching the schema
- 15-20 seed tracks with specific slot + reason
- Slots: morning_anchor, morning_energy, focus_deep, focus_light, discovery_new_artist, discovery_genre, energy_boost, wind_down, late_night
- Reasons must reference user data (affinity, completion, genre, recency)
- Playlist updates: specify which auto-playlists to refresh and how many tracks to add/remove
- discovery_ratio 0.1-0.3, repeat_comfort_ratio 0.2-0.4
- Focus genres from user's taste profile
- New artist exploration: specific directions like "Similar to Big Thief" or "90s Alt-Rock deep cuts"
"""

USER_PROMPT_TEMPLATE = """User Profile Context:
- Top Artists (affinity): {top_artists}
- Top Genres (%): {top_genres}
- Recent Plays (7d): {recent_plays}
- Completion Rate: {completion_rate:.1f}%
- Skip Rate: {skip_rate:.1f}%
- Time-of-Day Preferences: {tod_prefs}
- Active Playlists (14d): {active_playlists}
- Listening Streak: {streak} days
- Collaborative Recs: {collab_recs}

Generate a daily blueprint for {today}."""


# ===== SERVICE =====

class BlueprintService:
    def __init__(self):
        self._client = None
        self.model = settings.GROQ_MODEL

    def _get_client(self):
        if self._client is None and settings.GROQ_API_KEY:
            self._client = instructor.from_openai(
                AsyncOpenAI(
                    api_key=settings.GROQ_API_KEY,
                    base_url="https://api.groq.com/openai/v1"
                ),
                mode=instructor.Mode.JSON
            )
        return self._client

    async def generate_blueprint(self, db: AsyncSession, profile_id: uuid.UUID) -> DailyBlueprint:
        """Generate daily blueprint with quota check."""
        today = date.today()
        
        # Check existing
        existing = await db.execute(
            select(DailyBlueprint).where(
                DailyBlueprint.profile_id == profile_id,
                DailyBlueprint.date == today
            )
        )
        bp = existing.scalar_one_or_none()
        if bp:
            return bp

        # Check quota
        if not await self._check_quota(profile_id):
            # Fallback: rule-based blueprint
            return await self._generate_fallback_blueprint(db, profile_id)

        # Gather context
        context = await self._gather_context(db, profile_id)
        
        # Generate via LLM
        prompt = USER_PROMPT_TEMPLATE.format(
            today=today.isoformat(),
            **context
        )
        
        try:
            client = self._get_client()
            if not client:
                return await self._generate_fallback_blueprint(db, profile_id)
            response = await client.chat.completions.create(
                model=self.model,
                response_model=BlueprintResponse,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=2048
            )
            
            # Hydrate seed tracks with iTunes metadata
            seed_tracks = await self._hydrate_tracks(response.seed_tracks)
            
            # Convert PlaylistUpdate objects to dicts
            playlist_updates = {
                k: v.model_dump() for k, v in response.playlist_updates.items()
            }
            
            # Create blueprint
            bp = DailyBlueprint(
                profile_id=profile_id,
                date=today,
                strategy=response.strategy.model_dump(),
                seed_tracks=seed_tracks,
                playlist_updates=playlist_updates,
                llm_tokens_used=1500  # Approximate
            )
            db.add(bp)
            await db.flush()
            
            # Consume quota
            await self._consume_quota(profile_id, 1500)
            
            return bp
            
        except Exception as e:
            print(f"Blueprint generation failed: {e}")
            return await self._generate_fallback_blueprint(db, profile_id)

    async def _gather_context(self, db: AsyncSession, profile_id: uuid.UUID) -> dict:
        top_artists = await get_top_affinity_artists(db, profile_id, 10)
        top_genres = await get_taste_profile(db, profile_id, 5)
        recent_plays = await get_recent_plays(db, profile_id, 30)
        completion_rate, skip_rate = await get_completion_stats(db, profile_id)
        tod_prefs = await get_tod_genres(db, profile_id)
        active_playlists = await get_active_playlists(db, profile_id)
        streak = await get_listening_streak(db, profile_id)
        collab_recs = await get_collaborative_recommendations(db, profile_id, 3)

        return {
            "top_artists": json.dumps(top_artists),
            "top_genres": json.dumps(top_genres),
            "recent_plays": json.dumps(recent_plays),
            "completion_rate": completion_rate,
            "skip_rate": skip_rate,
            "tod_prefs": json.dumps(tod_prefs),
            "active_playlists": json.dumps(active_playlists),
            "streak": streak,
            "collab_recs": json.dumps(collab_recs),
        }

    async def _hydrate_tracks(self, seeds: list[SeedTrack]) -> list[dict]:
        """Enrich seed tracks with iTunes metadata (track_id, artwork, etc.)."""
        search = SearchService()
        hydrated = []
        
        for seed in seeds:
            try:
                tracks = await search.search_tracks(f"{seed.artist} {seed.track}", limit=1)
                if tracks:
                    t = tracks[0]
                    hydrated.append({
                        "track": seed.track,
                        "artist": seed.artist,
                        "slot": seed.slot,
                        "reason": seed.reason,
                        "track_id": t.track_id,
                        "album": t.album,
                        "artwork_url": t.artwork_url,
                        "duration_ms": t.duration_ms,
                        "genre": t.genre,
                    })
                else:
                    hydrated.append(seed.model_dump())
            except Exception:
                hydrated.append(seed.model_dump())
        
        return hydrated

    async def _check_quota(self, profile_id: uuid.UUID) -> bool:
        """Check if user has quota for blueprint generation."""
        return await quota_service.check_groq_quota(1500)

    async def _consume_quota(self, profile_id: uuid.UUID, tokens: int):
        await quota_service.consume_groq_quota(tokens)
        await quota_service.consume_user_blueprint_quota(profile_id)

    async def _generate_fallback_blueprint(self, db: AsyncSession, profile_id: uuid.UUID) -> DailyBlueprint:
        """Rule-based blueprint when LLM quota exhausted."""
        context = await self._gather_context(db, profile_id)
        
        # Simple rule-based strategy
        top_artists = json.loads(context["top_artists"])
        top_genres = json.loads(context["top_genres"])
        recent = json.loads(context["recent_plays"])
        
        # Build seed tracks from top artists + recent
        seeds = []
        for i, artist in enumerate(top_artists[:5]):
            seeds.append({
                "track": f"Top track by {artist['artist_name']}",
                "artist": artist['artist_name'],
                "slot": "morning_anchor" if i == 0 else "focus_deep",
                "reason": f"High affinity ({artist['affinity_score']:.0f})"
            })
        
        for genre in top_genres[:2]:
            seeds.append({
                "track": f"Discovery: {genre['genre']}",
                "artist": "Various",
                "slot": "discovery_genre",
                "reason": f"Top genre ({genre['percentage']:.1f}%)"
            })

        bp = DailyBlueprint(
            profile_id=profile_id,
            date=date.today(),
            strategy={
                "mood_arc": ["energetic_morning", "focus_afternoon", "wind_down_evening"],
                "focus_genres": [g["genre"] for g in top_genres[:3]],
                "discovery_ratio": 0.2,
                "repeat_comfort_ratio": 0.3,
                "new_artist_exploration": ["Similar to top artists", "Genre deep cuts"]
            },
            seed_tracks=seeds[:20],
            playlist_updates={
                "Daily Mix": {"add": 5, "remove_stale": 3},
                "Hidden Gems": {"add": 3}
            },
            llm_tokens_used=0
        )
        db.add(bp)
        await db.flush()
        return bp


async def get_today_blueprint(profile_id: uuid.UUID, db: AsyncSession) -> Optional[DailyBlueprint]:
    """Get today's blueprint, generating if needed."""
    today = date.today()
    result = await db.execute(
        select(DailyBlueprint).where(
            DailyBlueprint.profile_id == profile_id,
            DailyBlueprint.date == today
        )
    )
    bp = result.scalar_one_or_none()
    if not bp:
        bp = await blueprint_service.generate_blueprint(db, profile_id)
    return bp


async def update_blueprint_runtime(profile_id: uuid.UUID, db: AsyncSession, completed: bool, skipped: bool):
    """Update today's blueprint runtime stats after a playback event."""
    today = date.today()
    result = await db.execute(
        select(DailyBlueprint).where(
            DailyBlueprint.profile_id == profile_id,
            DailyBlueprint.date == today
        )
    )
    bp = result.scalar_one_or_none()
    if not bp:
        return
    
    stats = bp.runtime_stats or {}
    stats["total_tracks_played"] = stats.get("total_tracks_played", 0) + 1
    if completed:
        stats["completed"] = stats.get("completed", 0) + 1
    if skipped:
        stats["skipped"] = stats.get("skipped", 0) + 1
    stats["skip_rate"] = round(
        stats.get("skipped", 0) / max(stats.get("total_tracks_played", 1), 1) * 100, 1
    )
    bp.runtime_stats = stats
    await db.flush()


blueprint_service = BlueprintService()