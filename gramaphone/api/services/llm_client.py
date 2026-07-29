import json
import os
from typing import Optional
from dataclasses import dataclass
from groq import Groq
from pydantic import BaseModel, Field
from api.config import settings


# ===== STRUCTURED OUTPUT SCHEMAS =====

class SeedTrack(BaseModel):
    track: str
    artist: str
    slot: str = Field(pattern="^(morning|afternoon|evening|late_night|discovery|comfort|pivot)$")
    reason: str


class PlaylistUpdate(BaseModel):
    add: int = Field(ge=0, le=10)
    remove_stale: int = Field(default=0, ge=0, le=5)
    create_new: Optional[str] = None


class BlueprintStrategy(BaseModel):
    mood_arc: list[str] = Field(min_length=3, max_length=5)
    focus_genres: list[str] = Field(min_length=2, max_length=4)
    discovery_ratio: float = Field(ge=0.1, le=0.3)
    repeat_comfort_ratio: float = Field(ge=0.2, le=0.4)
    new_artist_exploration: list[str] = Field(min_length=1, max_length=3)
    seed_tracks: list[SeedTrack] = Field(min_length=12, max_length=20)
    playlist_updates: dict[str, PlaylistUpdate] = Field(default_factory=dict)


class BlueprintResponse(BaseModel):
    strategy: BlueprintStrategy


# ===== GROQ CLIENT =====

SYSTEM_PROMPT = """You are a music curation AI. Generate a daily listening blueprint as valid JSON.

OUTPUT ONLY VALID JSON MATCHING THE SCHEMA. NO EXTRA TEXT.

Rules:
1. mood_arc: 3-4 slots from ["energetic_morning", "focus_afternoon", "wind_down_evening", "late_night_chill"]
2. focus_genres: 2-3 specific genres from user's taste
3. discovery_ratio: 0.1-0.3 (fraction of new music)
4. repeat_comfort_ratio: 0.2-0.4 (fraction of favorites)
5. new_artist_exploration: 1-3 specific directions like "Similar to Big Thief" or "90s Alt-Rock deep cuts"
6. seed_tracks: 12-20 tracks with slot (morning/afternoon/evening/late_night/discovery/comfort) and reason
7. playlist_updates: which playlists to refresh and how many tracks to add/remove

Slot mapping:
- morning: 6-11am → energetic_morning
- afternoon: 12-16pm → focus_afternoon
- evening: 17-20pm → wind_down_evening
- late_night: 21-5am → late_night_chill
- discovery: new music exploration
- comfort: familiar favorites"""


@dataclass
class BlueprintContext:
    top_artists: list[dict]  # [{"artist_name": "...", "affinity_score": 123.4}]
    top_genres: list[dict]  # [{"genre": "...", "percentage": 45.2}]
    recent_plays: list[dict]  # [{"title": "...", "artist": "...", "completed": true, "skipped": false}]
    completion_rate: float
    skip_rate: float
    tod_prefs: list[dict]  # [{"period": "morning", "genres": ["Indie Rock"]}]
    active_playlists: list[str]  # Playlist names visited recently
    listening_streak: int


class GroqBlueprintClient:
    def __init__(self):
        self.client = Groq(api_key=settings.GROQ_API_KEY)
        self.model = settings.GROQ_MODEL
        self.max_tokens = settings.GROQ_MAX_TOKENS
        self.temperature = settings.GROQ_TEMPERATURE

    def _build_user_prompt(self, ctx: BlueprintContext) -> str:
        return f"""User Profile:
- Top Artists: {json.dumps(ctx.top_artists[:10])}
- Top Genres: {json.dumps(ctx.top_genres[:5])}
- Recent Plays (7d): {json.dumps(ctx.recent_plays[:20])}
- Completion Rate: {ctx.completion_rate:.1f}%
- Skip Rate: {ctx.skip_rate:.1f}%
- Time-of-Day Preferences: {json.dumps(ctx.tod_prefs)}
- Active Playlists: {ctx.active_playlists}
- Listening Streak: {ctx.listening_streak} days

Generate a daily blueprint matching the schema. Be specific with track names where possible (use known catalog)."""

    async def generate_blueprint(self, ctx: BlueprintContext) -> BlueprintResponse:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": self._build_user_prompt(ctx)}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            return BlueprintResponse.model_validate(data)
        except Exception as e:
            raise RuntimeError(f"Blueprint generation failed: {e}")

    def generate_blueprint_sync(self, ctx: BlueprintContext) -> BlueprintResponse:
        """Synchronous version for background workers."""
        return self.generate_blueprint(ctx)


# ===== FALLBACK (RULE-BASED) =====

def generate_fallback_blueprint(ctx: BlueprintContext) -> BlueprintResponse:
    """Generate blueprint without LLM when quota exhausted."""
    top_artists = [a["artist_name"] for a in ctx.top_artists[:5]]
    top_genres = [g["genre"] for g in ctx.top_genres[:3]]
    
    # Build seed tracks from known data
    seeds = []
    for i, artist in enumerate(top_artists):
        slot = ["morning", "afternoon", "evening", "discovery", "comfort"][i % 5]
        seeds.append(SeedTrack(
            track=f"Top track by {artist}",
            artist=artist,
            slot=slot,
            reason=f"High affinity artist ({ctx.top_artists[i]['affinity_score']:.0f} score)"
        ))
    
    # Add discovery seeds
    for genre in top_genres[:2]:
        seeds.append(SeedTrack(
            track=f"New {genre} discovery",
            artist="Various",
            slot="discovery",
            reason=f"Explore {genre} based on {top_genres[0]['percentage']:.0f}% taste share"
        ))

    strategy = BlueprintStrategy(
        mood_arc=["energetic_morning", "focus_afternoon", "wind_down_evening"],
        focus_genres=top_genres,
        discovery_ratio=0.2,
        repeat_comfort_ratio=0.3,
        new_artist_exploration=[f"Similar to {top_artists[0]}" if top_artists else "Indie discoveries"],
        seed_tracks=seeds[:18],
        playlist_updates={
            "Daily Mix": PlaylistUpdate(add=5, remove_stale=3),
            "Hidden Gems": PlaylistUpdate(add=3),
        }
    )
    
    return BlueprintResponse(strategy=strategy)