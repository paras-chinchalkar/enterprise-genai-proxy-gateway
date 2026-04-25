"""
rate_limiter.py — Department-level rate limiting using Redis.

Uses a fixed-window counter per department. Falls back gracefully to 
allow-all if Redis is unavailable (so a missing Redis never kills prod traffic).

Resume claim: "Designed cost tracking and department-level rate limiting 
               using LiteLLM metrics and Redis."
"""
import os
import time
import redis
from typing import Optional

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Requests per minute per department (configurable per key via env)
RATE_LIMIT_RPM = int(os.getenv("RATE_LIMIT_RPM", "20"))

_redis_client: Optional[redis.Redis] = None


def _get_redis() -> Optional[redis.Redis]:
    """Lazy-connect to Redis. Returns None if Redis is unavailable."""
    global _redis_client
    if _redis_client is not None:
        try:
            _redis_client.ping()
            return _redis_client
        except Exception:
            _redis_client = None

    try:
        client = redis.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        _redis_client = client
        print(f"[RateLimiter] Connected to Redis at {REDIS_URL}")
        return client
    except Exception as e:
        print(f"[RateLimiter] Redis unavailable ({e}). Rate limiting disabled (fail-open).")
        return None


def check_rate_limit(department: str) -> tuple[bool, dict]:
    """
    Fixed-window rate limiter per department (per minute).
    
    Returns:
        (is_allowed: bool, headers: dict)  — headers contain X-RateLimit-* info
    """
    r = _get_redis()
    if r is None:
        # Redis unavailable → fail open, still pass the request
        return True, {"X-RateLimit-Status": "disabled"}

    window_key = f"ratelimit:{department}:{int(time.time() // 60)}"

    try:
        pipe = r.pipeline()
        pipe.incr(window_key)
        pipe.expire(window_key, 60)
        results = pipe.execute()
        current_count = results[0]
    except Exception as e:
        print(f"[RateLimiter] Redis error: {e}. Failing open.")
        return True, {"X-RateLimit-Status": "error"}

    remaining = max(0, RATE_LIMIT_RPM - current_count)
    headers = {
        "X-RateLimit-Limit": str(RATE_LIMIT_RPM),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Window": "60s",
        "X-RateLimit-Department": department,
    }

    if current_count > RATE_LIMIT_RPM:
        return False, headers

    return True, headers


def get_redis_cache(key: str) -> Optional[str]:
    """Retrieve a cached LLM response from Redis."""
    r = _get_redis()
    if r is None:
        return None
    try:
        return r.get(key)
    except Exception:
        return None


def set_redis_cache(key: str, value: str, ttl: int = 3600):
    """Cache an LLM response in Redis with a TTL (default 1 hour)."""
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(key, ttl, value)
    except Exception as e:
        print(f"[RateLimiter] Cache write failed: {e}")


def get_department_request_count(department: str) -> int:
    """Get current-minute request count for a department (for dashboard)."""
    r = _get_redis()
    if r is None:
        return -1
    window_key = f"ratelimit:{department}:{int(time.time() // 60)}"
    try:
        val = r.get(window_key)
        return int(val) if val else 0
    except Exception:
        return -1
