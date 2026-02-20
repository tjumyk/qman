"""Redis-based caching for Docker container/image lists to reduce expensive API calls.

Given that we track Docker events (container create/remove) via sync_from_docker_events()
every 120 seconds, we can cache container lists for longer periods (5-10 minutes) and
invalidate the cache when events are detected. This significantly reduces Docker API load
while maintaining data freshness through event-driven invalidation.
"""

import json
import time
from typing import Any

from app.utils import get_logger

logger = get_logger(__name__)

# Cache keys
_CACHE_KEY_CONTAINERS = "docker:containers:list"
_CACHE_KEY_IMAGES = "docker:images:list"
_CACHE_KEY_LAST_INVALIDATION = "docker:cache:last_invalidation"

# Default TTL: 10 minutes (600 seconds)
# This is safe because:
# - Event detection runs every 120 seconds and invalidates cache on changes
# - Reconciliation still happens periodically via sync tasks
# - Even if events are missed, TTL ensures cache refreshes within 10 minutes
# Can be overridden via DOCKER_QUOTA_CACHE_TTL_SECONDS config
_DEFAULT_TTL_SECONDS = 600  # 10 minutes


def _get_cache_ttl() -> int:
    """Get cache TTL from config or default."""
    try:
        from flask import current_app
        ttl = current_app.config.get("DOCKER_QUOTA_CACHE_TTL_SECONDS")
        if ttl is not None:
            return int(ttl)
    except Exception:
        pass
    return _DEFAULT_TTL_SECONDS


def _get_redis_client():
    """Get Redis client from Celery broker URL or return None if Redis unavailable."""
    try:
        import redis
        from flask import current_app
        
        # Try to get Redis URL from Flask app config (Celery broker URL)
        try:
            broker_url = current_app.config.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        except RuntimeError:
            # current_app not available (e.g., outside Flask request context)
            logger.debug("Redis cache: Flask app context not available")
            return None
        
        if not broker_url or not broker_url.startswith("redis://"):
            logger.debug("Redis cache: CELERY_BROKER_URL not set or not a redis:// URL")
            return None
        
        # Parse Redis URL and create client
        # Format: redis://[password@]host[:port][/db]
        from urllib.parse import urlparse
        parsed = urlparse(broker_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        db = int(parsed.path.lstrip("/")) if parsed.path else 0
        password = parsed.password
        
        client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=False,  # We'll handle encoding ourselves
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        # Test connection
        client.ping()
        return client
    except ImportError:
        logger.warning("Redis cache: redis module not installed")
        return None
    except Exception as e:
        logger.debug("Redis cache unavailable: %s", e)
        return None


def get_cached_containers(ttl_seconds: int | None = None) -> list[dict[str, Any]] | None:
    """Get cached container list if available and not expired. Returns None if cache miss or Redis unavailable."""
    if ttl_seconds is None:
        ttl_seconds = _get_cache_ttl()
    
    redis_client = _get_redis_client()
    if not redis_client:
        return None
    
    try:
        cached_data = redis_client.get(_CACHE_KEY_CONTAINERS)
        if cached_data:
            data = json.loads(cached_data.decode("utf-8"))
            cached_time = data.get("timestamp", 0)
            age_seconds = time.time() - cached_time
            if age_seconds < ttl_seconds:
                logger.info("Cache hit: containers list (age=%.1fs, count=%d)", age_seconds, len(data.get("containers", [])))
                return data.get("containers", [])
            else:
                logger.info("Cache expired: containers list (age=%.1fs, ttl=%ds)", age_seconds, ttl_seconds)
        else:
            logger.debug("Cache miss: containers list (no cached data)")
        return None
    except Exception as e:
        logger.warning("Cache read failed: %s", e)
        return None


def set_cached_containers(containers: list[dict[str, Any]], ttl_seconds: int | None = None) -> None:
    """Cache container list with TTL."""
    if ttl_seconds is None:
        ttl_seconds = _get_cache_ttl()
    
    redis_client = _get_redis_client()
    if not redis_client:
        logger.debug("Cache write skipped: Redis unavailable")
        return
    
    try:
        data = {
            "timestamp": time.time(),
            "containers": containers,
        }
        redis_client.setex(
            _CACHE_KEY_CONTAINERS,
            ttl_seconds,
            json.dumps(data),
        )
        logger.info("Cached containers list (%d containers, ttl=%ds)", len(containers), ttl_seconds)
    except Exception as e:
        logger.warning("Cache write failed: %s", e)


def invalidate_container_cache() -> None:
    """Invalidate container cache (call when Docker events indicate container changes)."""
    redis_client = _get_redis_client()
    if not redis_client:
        return
    
    try:
        redis_client.delete(_CACHE_KEY_CONTAINERS)
        redis_client.set(_CACHE_KEY_LAST_INVALIDATION, time.time())
        logger.debug("Invalidated container cache")
    except Exception as e:
        logger.debug("Cache invalidation failed: %s", e)


def get_cached_images(ttl_seconds: int | None = None) -> list[dict[str, Any]] | None:
    """Get cached image list if available and not expired. Returns None if cache miss or Redis unavailable."""
    if ttl_seconds is None:
        ttl_seconds = _get_cache_ttl()
    
    redis_client = _get_redis_client()
    if not redis_client:
        return None
    
    try:
        cached_data = redis_client.get(_CACHE_KEY_IMAGES)
        if cached_data:
            data = json.loads(cached_data.decode("utf-8"))
            cached_time = data.get("timestamp", 0)
            age_seconds = time.time() - cached_time
            if age_seconds < ttl_seconds:
                logger.debug("Cache hit: images list (age=%.1fs)", age_seconds)
                return data.get("images", [])
            else:
                logger.debug("Cache expired: images list (age=%.1fs, ttl=%ds)", age_seconds, ttl_seconds)
        return None
    except Exception as e:
        logger.debug("Cache read failed: %s", e)
        return None


def set_cached_images(images: list[dict[str, Any]], ttl_seconds: int | None = None) -> None:
    """Cache image list with TTL."""
    if ttl_seconds is None:
        ttl_seconds = _get_cache_ttl()
    
    redis_client = _get_redis_client()
    if not redis_client:
        return
    
    try:
        data = {
            "timestamp": time.time(),
            "images": images,
        }
        redis_client.setex(
            _CACHE_KEY_IMAGES,
            ttl_seconds,
            json.dumps(data),
        )
        logger.debug("Cached images list (%d images, ttl=%ds)", len(images), ttl_seconds)
    except Exception as e:
        logger.debug("Cache write failed: %s", e)


def invalidate_image_cache() -> None:
    """Invalidate image cache (call when Docker events indicate image changes)."""
    redis_client = _get_redis_client()
    if not redis_client:
        return
    
    try:
        redis_client.delete(_CACHE_KEY_IMAGES)
        redis_client.set(_CACHE_KEY_LAST_INVALIDATION, time.time())
        logger.debug("Invalidated image cache")
    except Exception as e:
        logger.debug("Cache invalidation failed: %s", e)
