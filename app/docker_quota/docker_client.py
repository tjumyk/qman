"""Docker API/CLI client for listing containers, images, and disk usage (slave).

Note on timeouts: Docker API requests can take ~1 minute to complete. The collect_events_since()
function has a configurable timeout (default 90s). Other Docker SDK calls (list_containers,
get_system_df, etc.) use the SDK's default timeout (no timeout by default, waits indefinitely).
If you need explicit timeouts for all Docker operations, configure the Docker client with
timeout parameters when creating it.

Note on caching: list_containers() and list_images() use Redis cache with 10-minute TTL.
Cache is invalidated when Docker events indicate container/image changes. This significantly
reduces Docker API load while maintaining freshness through event-driven invalidation.
"""

import time
from typing import Any

from app.utils import get_logger

logger = get_logger(__name__)


def get_docker_data_root(base_url: str = "unix://var/run/docker.sock") -> str:
    """Return Docker data root (e.g. /var/lib/docker). Uses 'docker info' or default."""
    try:
        import docker
        client = docker.from_env()
        try:
            info = client.info()
            return info.get("DockerRootDir") or "/var/lib/docker"
        finally:
            client.close()
    except Exception as e:
        logger.warning("Could not get Docker data root: %s", e)
    return "/var/lib/docker"


def list_containers(all_containers: bool = True, use_cache: bool = True) -> list[dict[str, Any]]:
    """List containers (running and stopped). Returns list of {id, name, image_id, created, labels}.
    
    Note: Avoids accessing c.image.id (which triggers expensive inspect_image API call). Instead uses
    image ID from container attributes (c.attrs) which is already loaded.
    
    Args:
        all_containers: If True, include stopped containers.
        use_cache: If True, check Redis cache first (default True). Set False to force fresh fetch.
    
    Returns:
        List of container dicts. Uses cache if available and not expired (10-minute TTL).
        Cache is invalidated when Docker events indicate container changes.
    """
    start_time = time.time()
    
    # Try cache first (if enabled)
    if use_cache:
        try:
            from app.docker_quota.cache import get_cached_containers, set_cached_containers
            cached = get_cached_containers()
            if cached is not None:
                elapsed = time.time() - start_time
                logger.info("Docker list_containers: cache hit (took %.3fs, count=%d)", elapsed, len(cached))
                return cached
        except Exception as e:
            logger.debug("Cache check failed, falling back to Docker API: %s", e)
    
    # Cache miss or cache disabled: fetch from Docker API
    try:
        import docker
        client_start = time.time()
        client = docker.from_env()
        client_init_time = time.time() - client_start
        
        list_start = time.time()
        containers = client.containers.list(all=all_containers)
        list_time = time.time() - list_start
        
        parse_start = time.time()
        result = []
        for c in containers:
            # Get image ID from attrs to avoid lazy-loading API call (c.image.id triggers inspect_image)
            # Image ID is in c.attrs["Image"] (short ID) or c.attrs["Config"]["Image"] (image name)
            # For full image ID, we'd need inspect, but short ID is usually sufficient
            image_id = None
            attrs = c.attrs
            if "Image" in attrs:
                image_id = attrs["Image"]  # Short image ID (e.g. "sha256:abc123...")
            elif "Config" in attrs and "Image" in attrs["Config"]:
                # Fallback: image name/tag (less ideal but avoids API call)
                image_id = attrs["Config"]["Image"]
            result.append({
                "id": c.id,
                "short_id": c.short_id,
                "name": (c.name or ""),
                "image": image_id,
                "created": attrs.get("Created"),
                "labels": attrs.get("Labels") or {},
            })
        parse_time = time.time() - parse_start
        
        # Cache the result
        if use_cache:
            try:
                set_cached_containers(result)
            except Exception as e:
                logger.debug("Failed to cache containers list: %s", e)
        
        total_time = time.time() - start_time
        logger.debug(
            "Docker list_containers: total=%.2fs (client_init=%.2fs, list=%.2fs, parse=%.2fs, count=%d)",
            total_time, client_init_time, list_time, parse_time, len(result)
        )
        return result
    except Exception as e:
        elapsed = time.time() - start_time
        logger.warning("Docker list containers failed: %s (took %.2fs)", e, elapsed)
        return []


def list_images(use_cache: bool = True) -> list[dict[str, Any]]:
    """List images. Returns list of {id, short_id, size, created}.
    
    Args:
        use_cache: If True, check Redis cache first (default True). Set False to force fresh fetch.
    
    Returns:
        List of image dicts. Uses cache if available and not expired (10-minute TTL).
        Cache is invalidated when Docker events indicate image changes.
    """
    start_time = time.time()
    
    # Try cache first (if enabled)
    if use_cache:
        try:
            from app.docker_quota.cache import get_cached_images, set_cached_images
            cached = get_cached_images()
            if cached is not None:
                elapsed = time.time() - start_time
                logger.info("Docker list_images: cache hit (took %.3fs, count=%d)", elapsed, len(cached))
                return cached
        except Exception as e:
            logger.debug("Cache check failed, falling back to Docker API: %s", e)
    
    # Cache miss or cache disabled: fetch from Docker API
    try:
        import docker
        client = docker.from_env()
        try:
            images = client.images.list()
            result = [
                {
                    "id": img.id,
                    "short_id": img.short_id,
                    "size": img.attrs.get("Size") or 0,
                    "created": img.attrs.get("Created"),
                }
                for img in images
            ]
            # Cache the result
            if use_cache:
                try:
                    set_cached_images(result)
                except Exception as e:
                    logger.debug("Failed to cache images list: %s", e)
            elapsed = time.time() - start_time
            logger.debug("Docker list_images: total=%.2fs (count=%d)", elapsed, len(result))
            return result
        finally:
            client.close()
    except Exception as e:
        elapsed = time.time() - start_time
        logger.warning("Docker list images failed: %s (took %.2fs)", e, elapsed)
        return []


def _parse_created_iso(created: str | None) -> float:
    """Parse Docker Created ISO string to Unix timestamp. Returns 0 if missing/invalid."""
    if not created:
        return 0.0
    try:
        import datetime
        s = created.replace("Z", "+00:00")
        # Python's fromisoformat handles .microseconds and +00:00
        dt = datetime.datetime.fromisoformat(s)
        return dt.timestamp()
    except Exception:
        return 0.0


def get_system_df(container_ids: list[str] | None = None) -> dict[str, Any]:
    """Run 'docker system df -v' equivalent: per-container and per-image sizes. Returns dict with Containers, Images.
    
    Args:
        container_ids: Optional list of container IDs to inspect. If None, will list all containers first.
                       This avoids duplicate list_containers() calls when container list is already known.
    """
    start_time = time.time()
    try:
        import docker
        client_start = time.time()
        client = docker.from_env()
        client_init_time = time.time() - client_start
        
        # Docker SDK doesn't expose "system df -v" directly; build from containers + images
        if container_ids is None:
            list_containers_start = time.time()
            containers = client.containers.list(all=True)
            list_containers_time = time.time() - list_containers_start
            container_ids_list = [c.id for c in containers]
        else:
            list_containers_time = 0.0
            container_ids_list = container_ids
        
        list_images_start = time.time()
        images = client.images.list()
        list_images_time = time.time() - list_images_start
        
        # Size of a container = size of its writable layer (from inspect)
        inspect_start = time.time()
        container_sizes: dict[str, int] = {}
        inspect_times: list[float] = []
        for cid in container_ids_list:
            inspect_one_start = time.time()
            try:
                inspect = client.api.inspect_container(cid, size=True)
                size_rw = inspect.get("SizeRw") or 0
                container_sizes[cid] = size_rw
            except Exception:
                container_sizes[cid] = 0
            inspect_times.append(time.time() - inspect_one_start)
        inspect_time = time.time() - inspect_start
        
        parse_images_start = time.time()
        image_sizes = {img.id: (img.attrs.get("Size") or 0) for img in images}
        parse_images_time = time.time() - parse_images_start
        
        total_time = time.time() - start_time
        avg_inspect = sum(inspect_times) / len(inspect_times) if inspect_times else 0
        max_inspect = max(inspect_times) if inspect_times else 0
        logger.info(
            "Docker get_system_df: total=%.2fs (client_init=%.2fs, list_containers=%.2fs, list_images=%.2fs, "
            "inspect_containers=%.2fs [avg=%.3fs, max=%.3fs, count=%d], parse_images=%.2fs)",
            total_time, client_init_time, list_containers_time, list_images_time,
            inspect_time, avg_inspect, max_inspect, len(container_ids_list), parse_images_time
        )
        return {
            "containers": container_sizes,
            "images": image_sizes,
        }
    except Exception as e:
        elapsed = time.time() - start_time
        logger.warning("Docker system df failed: %s (took %.2fs)", e, elapsed)
        return {"containers": {}, "images": {}}


def stop_container(container_id: str) -> bool:
    """Stop a container. Returns True on success.
    
    Note: Container stop timeout is 60s to allow graceful shutdown even if Docker API is slow.
    """
    try:
        import docker
        client = docker.from_env()
        try:
            c = client.containers.get(container_id)
            c.stop(timeout=60)
            return True
        finally:
            client.close()
    except Exception as e:
        logger.warning("Docker stop container %s failed: %s", container_id, e)
        return False


def collect_events_since(since_ts: float, max_seconds: float = 90.0, max_events: int = 2000) -> list[dict[str, Any]]:
    """Collect Docker API events since given Unix timestamp. Returns list of {type, action, id, time_nano, ...}.
    Stops after max_seconds or when max_events is reached (events() is a blocking generator).
    
    Note: Docker API requests can take ~1 minute, so default max_seconds is 90 to avoid early abort.
    """
    try:
        import datetime
        import docker
        import threading
        since_dt = datetime.datetime.utcfromtimestamp(since_ts)
        client = docker.from_env()
        out: list[dict[str, Any]] = []
        done = threading.Event()

        def consume() -> None:
            try:
                for ev in client.events(since=since_dt, decode=True):
                    if done.is_set() or len(out) >= max_events:
                        break
                    out.append({
                        "type": ev.get("Type"),
                        "action": ev.get("Action"),
                        "id": ev.get("id") or ev.get("ID"),
                        "time_nano": ev.get("timeNano") or ev.get("time"),
                        "from": ev.get("from"),
                    })
            except Exception as e:
                logger.warning("Docker events stream error: %s", e)
            finally:
                try:
                    client.close()
                except Exception:
                    pass

        t = threading.Thread(target=consume, daemon=True)
        t.start()
        done.wait(timeout=max_seconds)
        done.set()
        # Allow extra time for thread cleanup if Docker API is slow
        t.join(timeout=5.0)
        return out
    except Exception as e:
        logger.warning("Docker events failed: %s", e)
        return []


def remove_container(container_id: str, force: bool = True) -> bool:
    """Remove a container (must be stopped first if force=False). Returns True on success."""
    try:
        import docker
        client = docker.from_env()
        try:
            c = client.containers.get(container_id)
            c.remove(force=force)
            return True
        finally:
            client.close()
    except Exception as e:
        logger.warning("Docker remove container %s failed: %s", container_id, e)
        return False


def get_image_layers_with_sizes(image_id: str) -> list[tuple[str, int]]:
    """Get layers and their sizes for an image. Returns [(layer_id, size_bytes), ...] in order (oldest first).
    Uses Docker API's inspect_image for layer IDs and history() for layer sizes.
    Note: history() returns layers in reverse order (newest first), so we reverse to match RootFS.Layers order.
    """
    start_time = time.time()
    try:
        import docker
        client_start = time.time()
        client = docker.from_env()
        client_init_time = time.time() - client_start
        
        # Get layer IDs (oldest first)
        inspect_start = time.time()
        inspect = client.api.inspect_image(image_id)
        inspect_time = time.time() - inspect_start
        
        rootfs = inspect.get("RootFS", {})
        layer_ids = rootfs.get("Layers", [])
        if not layer_ids:
            elapsed = time.time() - start_time
            logger.debug("Docker get_image_layers_with_sizes %s: total=%.2fs (no layers)", image_id[:12], elapsed)
            return []
        
        # Get layer sizes from history (newest first, so reverse)
        history_start = time.time()
        history = client.api.history(image_id)
        history_time = time.time() - history_start
        
        # history returns list of dicts with 'Size' field (incremental size added by each layer)
        # Match layers: RootFS.Layers[0] (oldest) -> history[-1] (oldest), RootFS.Layers[-1] (newest) -> history[0] (newest)
        parse_start = time.time()
        history_sizes = [h.get("Size", 0) for h in reversed(history)]  # Reverse to oldest first
        # Match layer_ids with sizes (pad if mismatch)
        result: list[tuple[str, int]] = []
        for i, layer_id in enumerate(layer_ids):
            size = history_sizes[i] if i < len(history_sizes) else 0
            result.append((layer_id, size))
        parse_time = time.time() - parse_start
        
        total_time = time.time() - start_time
        logger.debug(
            "Docker get_image_layers_with_sizes %s: total=%.2fs (client_init=%.2fs, inspect=%.2fs, history=%.2fs, parse=%.2fs, layers=%d)",
            image_id[:12], total_time, client_init_time, inspect_time, history_time, parse_time, len(result)
        )
        return result
    except Exception as e:
        elapsed = time.time() - start_time
        logger.warning("Docker get image layers failed for %s: %s (took %.2fs)", image_id[:12], e, elapsed)
        return []
