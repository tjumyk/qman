"""Redis-based caching for Docker container/image lists to reduce expensive API calls.

Given that we track Docker events (container create/remove) via sync_from_docker_events()
every 120 seconds, we can cache container lists for longer periods (5-10 minutes) and
invalidate the cache when events are detected. This significantly reduces Docker API load
while maintaining data freshness through event-driven invalidation.

Also provides Redis-based distributed locks for Docker API operations so that with
multiple gunicorn workers only one worker hits the Docker API at a time per operation.
"""

import json
import threading
import time
from contextlib import contextmanager
from typing import Any, Generator

from app.utils import get_logger

logger = get_logger(__name__)

# Cache keys
_CACHE_KEY_CONTAINERS = "docker:containers:list"
_CACHE_KEY_IMAGES = "docker:images:list"
_CACHE_KEY_SYSTEM_DF = "docker:system_df"
_CACHE_KEY_LAST_INVALIDATION = "docker:cache:last_invalidation"

# Default TTL: 5 minutes (300 seconds)
# This is safe because:
# - Sync task runs every 10 minutes (DOCKER_QUOTA_SYNC_INTERVAL_SECONDS) and can invalidate cache on changes
# - Enforcement task runs every 5 minutes but uses use_cache=False for correctness
# - TTL ensures cache refreshes even if sync misses events
# Can be overridden via DOCKER_QUOTA_CACHE_TTL_SECONDS config
_DEFAULT_TTL_SECONDS = 300  # 5 minutes


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


# Lock key prefix for Docker API operations (distributed across gunicorn workers)
_LOCK_PREFIX = "docker:lock:"

# Default: hold lock up to 2 minutes (Docker API can be slow), wait up to 3 minutes to acquire
_DEFAULT_LOCK_HOLD_SECONDS = 120
_DEFAULT_LOCK_WAIT_SECONDS = 180.0


@contextmanager
def redis_lock(
    lock_name: str,
    hold_timeout_seconds: int = _DEFAULT_LOCK_HOLD_SECONDS,
    wait_timeout_seconds: float = _DEFAULT_LOCK_WAIT_SECONDS,
    fallback_lock: threading.Lock | None = None,
) -> Generator[None, None, None]:
    """Context manager for a Redis-based distributed lock. Works across gunicorn workers.

    When Redis is available, uses redis.lock.Lock so only one process holds the lock.
    When Redis is unavailable, uses fallback_lock if provided (in-process serialization only).

    Args:
        lock_name: Name of the lock (e.g. "list_containers").
        hold_timeout_seconds: Max time the lock is held (auto-release to avoid deadlock).
        wait_timeout_seconds: Max time to wait to acquire the lock.
        fallback_lock: Optional threading.Lock to use when Redis is unavailable.
    """
    redis_client = _get_redis_client()
    if redis_client:
        try:
            from redis.lock import Lock as RedisLock

            key = _LOCK_PREFIX + lock_name
            lock = RedisLock(
                redis_client,
                key,
                timeout=hold_timeout_seconds,
                blocking=True,
                blocking_timeout=wait_timeout_seconds,
            )
            acquired = lock.acquire()
            if not acquired:
                logger.warning(
                    "Redis lock %s not acquired within %ss, using fallback",
                    lock_name,
                    wait_timeout_seconds,
                )
                if fallback_lock is not None:
                    with fallback_lock:
                        yield
                else:
                    yield
                return
            try:
                yield
            finally:
                try:
                    lock.release()
                except Exception as e:
                    logger.debug("Redis lock release failed (may have expired): %s", e)
        except Exception as e:
            logger.debug("Redis lock acquire failed, falling back: %s", e)
            if fallback_lock is not None:
                with fallback_lock:
                    yield
            else:
                yield
    else:
        if fallback_lock is not None:
            with fallback_lock:
                yield
        else:
            yield


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


# System DF cache TTL - configurable for production environments where df() API is slow
# Default 300s (5 minutes) balances freshness vs performance for large Docker environments
# where the df() API can take 10-20 seconds due to size calculations on TB of data.
# Can be overridden via DOCKER_QUOTA_DF_CACHE_TTL_SECONDS config
_DEFAULT_DF_TTL_SECONDS = 300  # 5 minutes


def _get_df_cache_ttl() -> int:
    """Get system df cache TTL from config or default."""
    try:
        from flask import current_app
        ttl = current_app.config.get("DOCKER_QUOTA_DF_CACHE_TTL_SECONDS")
        if ttl is not None:
            return int(ttl)
    except Exception:
        pass
    return _DEFAULT_DF_TTL_SECONDS


def get_cached_system_df(include_volumes: bool = False) -> dict[str, Any] | None:
    """Get cached system df result if available and not expired.
    
    Returns None if cache miss or Redis unavailable.
    Frontend APIs can use this for faster response; background tasks should bypass.
    TTL is configurable via DOCKER_QUOTA_DF_CACHE_TTL_SECONDS (default 300s).
    """
    redis_client = _get_redis_client()
    if not redis_client:
        return None
    
    ttl_seconds = _get_df_cache_ttl()
    cache_key = f"{_CACHE_KEY_SYSTEM_DF}:volumes={include_volumes}"
    try:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            data = json.loads(cached_data.decode("utf-8"))
            cached_time = data.get("timestamp", 0)
            age_seconds = time.time() - cached_time
            if age_seconds < ttl_seconds:
                logger.debug(
                    "Cache hit: system_df (age=%.1fs, containers=%d, images=%d)",
                    age_seconds,
                    len(data.get("result", {}).get("containers", {})),
                    len(data.get("result", {}).get("images", {})),
                )
                return data.get("result")
            else:
                logger.debug("Cache expired: system_df (age=%.1fs, ttl=%ds)", age_seconds, ttl_seconds)
        return None
    except Exception as e:
        logger.debug("Cache read failed (system_df): %s", e)
        return None


def set_cached_system_df(result: dict[str, Any], include_volumes: bool = False) -> None:
    """Cache system df result. TTL configurable via DOCKER_QUOTA_DF_CACHE_TTL_SECONDS (default 300s)."""
    redis_client = _get_redis_client()
    if not redis_client:
        return
    
    ttl_seconds = _get_df_cache_ttl()
    cache_key = f"{_CACHE_KEY_SYSTEM_DF}:volumes={include_volumes}"
    try:
        data = {
            "timestamp": time.time(),
            "result": result,
        }
        redis_client.setex(
            cache_key,
            ttl_seconds,
            json.dumps(data),
        )
        logger.debug(
            "Cached system_df (containers=%d, images=%d, ttl=%ds)",
            len(result.get("containers", {})),
            len(result.get("images", {})),
            ttl_seconds,
        )
    except Exception as e:
        logger.debug("Cache write failed (system_df): %s", e)


def invalidate_system_df_cache() -> None:
    """Invalidate system df cache (call when Docker events indicate changes)."""
    redis_client = _get_redis_client()
    if not redis_client:
        return
    
    try:
        # Delete both variants (with and without volumes)
        redis_client.delete(f"{_CACHE_KEY_SYSTEM_DF}:volumes=False")
        redis_client.delete(f"{_CACHE_KEY_SYSTEM_DF}:volumes=True")
        logger.debug("Invalidated system_df cache")
    except Exception as e:
        logger.debug("Cache invalidation failed (system_df): %s", e)
