from datetime import date
from typing import Optional
import uuid
from upstash_redis import Redis
from api.config import settings


class QuotaService:
    def __init__(self):
        self.redis: Optional[Redis] = None
        self.groq_daily_limit = settings.GROQ_DAILY_TOKEN_LIMIT
        self.per_user_daily = settings.PER_USER_DAILY_BLUEPRINTS

    async def init(self, redis_url: str = None, redis_token: str = None):
        redis_url = redis_url or settings.UPSTASH_REDIS_REST_URL
        redis_token = redis_token or settings.UPSTASH_REDIS_REST_TOKEN
        if redis_url and redis_token:
            self.redis = Redis(
                url=redis_url,
                token=redis_token
            )

    async def check_groq_quota(self, estimated_tokens: int = 1500) -> bool:
        """Check if global daily Groq token budget available."""
        if not self.redis:
            return True
        today = date.today().isoformat()
        key = f"quota:groq:tokens:{today}"
        used = await self.redis.get(key)
        used = int(used) if used else 0
        return (used + estimated_tokens) <= self.groq_daily_limit

    async def consume_groq_quota(self, tokens: int = 1500) -> bool:
        if not self.redis:
            return True
        today = date.today().isoformat()
        key = f"quota:groq:tokens:{today}"
        used = await self.redis.get(key)
        used = int(used) if used else 0
        if (used + tokens) > self.groq_daily_limit:
            return False
        await self.redis.incrby(key, tokens)
        await self.redis.expire(key, 86400)
        return True

    async def check_user_blueprint_quota(self, profile_id: uuid.UUID) -> bool:
        if not self.redis:
            return True
        today = date.today().isoformat()
        key = f"quota:blueprints:{today}:{profile_id}"
        count = await self.redis.get(key)
        return (int(count) if count else 0) < self.per_user_daily

    async def consume_user_blueprint_quota(self, profile_id: uuid.UUID) -> bool:
        if not self.redis:
            return True
        today = date.today().isoformat()
        key = f"quota:blueprints:{today}:{profile_id}"
        count = await self.redis.get(key)
        count = int(count) if count else 0
        if count >= self.per_user_daily:
            return False
        await self.redis.incr(key)
        await self.redis.expire(key, 86400)
        return True

    async def get_quota_status(self) -> dict:
        """Get current quota usage for monitoring."""
        if not self.redis:
            return {"available": True, "note": "Redis not configured"}
        
        today = date.today().isoformat()
        groq_used = await self.redis.get(f"quota:groq:tokens:{today}")
        
        return {
            "groq_tokens_used": int(groq_used) if groq_used else 0,
            "groq_tokens_limit": self.groq_daily_limit,
            "groq_tokens_remaining": self.groq_daily_limit - (int(groq_used) if groq_used else 0),
        }


quota_service = QuotaService()