"""Docker API/CLI client for listing containers, images, and disk usage (slave).

Note on timeouts: docker-py's default HTTP read timeout is 60 seconds for all API calls.
Heavy endpoints such as ``system/df`` can exceed that on busy hosts; ``get_system_df()`` uses
a longer timeout (default 180s, overridable via ``DOCKER_SYSTEM_DF_TIMEOUT``).
The collect_events_since() function has a separate configurable wall-clock limit (default 90s).

Note on caching: list_containers() and list_images() use Redis cache with 10-minute TTL.
Cache is invalidated when Docker events indicate container/image changes. This significantly
reduces Docker API load while maintaining freshness through event-driven invalidation.

Note on locking: Heavy operations (list_containers, list_images, get_system_df) use per-operation locks so that concurrent
requests do not all hit the Docker API at once. Locks are Redis-based so they work across gunicorn workers; if Redis
is unavailable, in-process threading locks are used as fallback. Cacheable operations use double-checked
locking: the first caller does the work and fills the cache; waiters then see a cache hit.
"""

import os
import threading
import time
from typing import Any

from app.docker_quota.cache import redis_lock
from app.utils import get_logger

logger = get_logger(__name__)

# Per-operation locks: Redis lock when available (cross-worker), else in-process fallback.
_lock_list_containers = threading.Lock()
_lock_list_images = threading.Lock()
_lock_system_df = threading.Lock()

# ``GET /system/df`` can run longer than docker-py's default 60s read timeout on large daemons.
_DEFAULT_SYSTEM_DF_TIMEOUT_SEC = 180


def _system_df_api_timeout_seconds() -> int:
    """Seconds for Docker client timeout during system df only (env DOCKER_SYSTEM_DF_TIMEOUT)."""
    raw = os.environ.get("DOCKER_SYSTEM_DF_TIMEOUT", str(_DEFAULT_SYSTEM_DF_TIMEOUT_SEC))
    try:
        n = int(raw, 10)
    except ValueError:
        return _DEFAULT_SYSTEM_DF_TIMEOUT_SEC
    return max(60, min(n, 3600))


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
    
    # Cache miss or cache disabled: fetch from Docker API (single flight under lock)
    with redis_lock("list_containers", fallback_lock=_lock_list_containers):
        # Double-check cache after acquiring lock (another thread may have filled it)
        if use_cache:
            try:
                from app.docker_quota.cache import get_cached_containers, set_cached_containers
                cached = get_cached_containers()
                if cached is not None:
                    elapsed = time.time() - start_time
                    logger.info("Docker list_containers: cache hit after lock (took %.3fs, count=%d)", elapsed, len(cached))
                    return cached
            except Exception:
                pass
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
                # Labels are in Config.Labels, not directly in attrs.Labels
                config_labels = (attrs.get("Config") or {}).get("Labels") or {}
                result.append({
                    "id": c.id,
                    "short_id": c.short_id,
                    "name": (c.name or ""),
                    "image": image_id,
                    "created": attrs.get("Created"),
                    "labels": config_labels,
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
    
    # Cache miss or cache disabled: fetch from Docker API (single flight under lock)
    with redis_lock("list_images", fallback_lock=_lock_list_images):
        if use_cache:
            try:
                from app.docker_quota.cache import get_cached_images, set_cached_images
                cached = get_cached_images()
                if cached is not None:
                    elapsed = time.time() - start_time
                    logger.info("Docker list_images: cache hit after lock (took %.3fs, count=%d)", elapsed, len(cached))
                    return cached
            except Exception:
                pass
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


def get_system_df(
    container_ids: list[str] | None = None,
    image_sizes: dict[str, int] | None = None,
    include_volumes: bool = False,
    use_cache: bool = False,
) -> dict[str, Any]:
    """Run 'docker system df -v' equivalent: per-container, per-image, and optionally per-volume sizes.

    Uses a single client.api.df() call to fetch all data efficiently, instead of making
    individual inspect calls per container (which is O(n) API calls).

    Args:
        container_ids: Deprecated/ignored. Previously used to avoid duplicate list_containers() calls.
                       Now all data comes from single df() call.
        image_sizes: Deprecated/ignored. Previously used to skip images.list().
                     Now all data comes from single df() call.
        include_volumes: If True, also include volume sizes in the result.
        use_cache: If True, check Redis cache first (60s TTL). Use for frontend APIs only.
                   Background tasks should use False (default) for accurate enforcement/sync.

    Returns:
        dict with keys:
        - "containers": {container_id: size_bytes}
        - "images": {image_id: size_bytes}
        - "volumes": {volume_name: {"size": int, "labels": dict, "ref_count": int}} (only if include_volumes=True)
    """
    start_time = time.time()
    
    # Check cache first if enabled (frontend APIs only)
    if use_cache:
        try:
            from app.docker_quota.cache import get_cached_system_df
            cached = get_cached_system_df(include_volumes=include_volumes)
            if cached is not None:
                elapsed = time.time() - start_time
                logger.debug("Docker get_system_df: cache hit (took %.3fs)", elapsed)
                return cached
        except Exception as e:
            logger.debug("Cache check failed, falling back to Docker API: %s", e)
    
    with redis_lock("system_df", fallback_lock=_lock_system_df):
        if use_cache:
            try:
                from app.docker_quota.cache import get_cached_system_df
                cached = get_cached_system_df(include_volumes=include_volumes)
                if cached is not None:
                    elapsed = time.time() - start_time
                    logger.debug("Docker get_system_df: cache hit after lock (took %.3fs)", elapsed)
                    return cached
            except Exception:
                pass
        try:
            import docker
            client_start = time.time()
            df_timeout = _system_df_api_timeout_seconds()
            client = docker.from_env(timeout=df_timeout)
            client_init_time = time.time() - client_start

            # Single df() call returns containers (with SizeRw), images (with Size), and volumes
            df_start = time.time()
            try:
                df_result = client.api.df()
            finally:
                client.close()
            df_time = time.time() - df_start

            # Extract container sizes from df result
            parse_start = time.time()
            df_containers = df_result.get("Containers") or []
            container_sizes_dict: dict[str, int] = {
                c["Id"]: (c.get("SizeRw") or 0) for c in df_containers
            }

            # Extract image sizes from df result
            df_images = df_result.get("Images") or []
            image_sizes_dict: dict[str, int] = {
                img["Id"]: (img.get("Size") or 0) for img in df_images
            }

            # Extract volume data if requested
            volumes_dict: dict[str, dict[str, Any]] = {}
            if include_volumes:
                volumes_list = df_result.get("Volumes") or []
                for vol in volumes_list:
                    vol_name = vol.get("Name")
                    if not vol_name:
                        continue
                    usage_data = vol.get("UsageData") or {}
                    volumes_dict[vol_name] = {
                        "size": usage_data.get("Size", 0) or 0,
                        "labels": vol.get("Labels") or {},
                        "ref_count": usage_data.get("RefCount", 0) or 0,
                    }
            parse_time = time.time() - parse_start

            total_time = time.time() - start_time
            total_container_bytes = sum(container_sizes_dict.values())
            total_image_bytes = sum(image_sizes_dict.values())
            total_volume_bytes = sum(v["size"] for v in volumes_dict.values()) if volumes_dict else 0
            containers_with_size = sum(1 for s in container_sizes_dict.values() if s > 0)

            log_msg = (
                "Docker get_system_df: total=%.2fs (client_init=%.2fs, df_api=%.2fs, parse=%.2fs) "
                "sizes: containers=%d bytes (%d with data, %d total), images=%d bytes (%d images)"
            )
            log_args: list[Any] = [
                total_time, client_init_time, df_time, parse_time,
                total_container_bytes, containers_with_size, len(container_sizes_dict),
                total_image_bytes, len(image_sizes_dict)
            ]
            if include_volumes:
                log_msg += ", volumes=%d bytes (%d volumes)"
                log_args.extend([total_volume_bytes, len(volumes_dict)])
            logger.info(log_msg, *log_args)

            result: dict[str, Any] = {
                "containers": container_sizes_dict,
                "images": image_sizes_dict,
            }
            if include_volumes:
                result["volumes"] = volumes_dict
            
            # Cache result for frontend APIs (only if caching was requested)
            if use_cache:
                try:
                    from app.docker_quota.cache import set_cached_system_df
                    set_cached_system_df(result, include_volumes=include_volumes)
                except Exception as cache_err:
                    logger.debug("Failed to cache system_df result: %s", cache_err)
            
            return result
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


def collect_events_since(since_ts: int, until_ts: int | None = None, max_seconds: float = 90.0, max_events: int = 2000) -> list[dict[str, Any]]:
    """Collect Docker API events since given Unix timestamp (in seconds) and until given Unix timestamp (in seconds, if provided). Returns list of {type, action, id, time_nano, ...}.
    Stops after max_seconds or when max_events is reached (events() is a blocking generator).
    
    Note: Docker API requests can take ~1 minute, so default max_seconds is 90 to avoid early abort.
    """
    try:
        import docker
        import threading

        if max_events <= 0:
            return []

        # ensure since_ts is int, until_ts is int if provided
        since_ts = int(since_ts) 
        until_ts = int(until_ts) if until_ts is not None else None

        out: list[dict[str, Any]] = []

        client = docker.from_env()
        try:
            # opens a real-time event stream, need to be closed by another thread
            event_stream = client.events(since=since_ts, until=until_ts, decode=True)

            def consume() -> None:
                try:
                    for ev in event_stream:
                        # ID is in Actor.ID, not directly in the event
                        actor = ev.get("Actor") or {}
                        actor_id = actor.get("ID") or ev.get("id") or ev.get("ID")
                        out.append({
                            "type": ev.get("Type"),
                            "action": ev.get("Action"),
                            "id": actor_id,
                            "time_nano": ev.get("timeNano") or ev.get("time"),
                            "from": ev.get("from"),
                            "actor_attributes": actor.get("Attributes") or {},
                        })
                        if len(out) >= max_events:
                            break
                except Exception as e:
                    logger.warning("Docker events stream error: %s", e)

            t = threading.Thread(target=consume, daemon=True)
            t.start()
            t.join(timeout=max_seconds)  # wait for at most max_seconds for events
            if t.is_alive():
                logger.warning("Docker events stream timed out after %s seconds", max_seconds)
            try:
                event_stream.close()  # unblocks consumer thread; double close is harmless
            except Exception:
                pass
            t.join(timeout=5.0)  # allow extra time for thread cleanup if Docker API is slow
            return list(out)  # return a copy to avoid possible modifications from consumer thread
        finally:
            try:
                client.close()
            except Exception:
                pass
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


def get_container_details() -> list[dict[str, Any]]:
    """Get detailed container info for display. Returns list of {id, name, image, status, created}.
    
    Fetches additional fields not included in list_containers() for UI display purposes.
    """
    start_time = time.time()
    try:
        import docker
        client = docker.from_env()
        try:
            containers = client.containers.list(all=True)
            result = []
            for c in containers:
                attrs = c.attrs
                config = attrs.get("Config") or {}
                state = attrs.get("State") or {}
                result.append({
                    "id": c.id,
                    "short_id": c.short_id,
                    "name": c.name or "",
                    "image": config.get("Image") or attrs.get("Image") or "",
                    "status": state.get("Status") or c.status or "unknown",
                    "created": attrs.get("Created"),
                    "labels": config.get("Labels") or {},
                })
            elapsed = time.time() - start_time
            logger.debug("Docker get_container_details: total=%.2fs (count=%d)", elapsed, len(result))
            return result
        finally:
            client.close()
    except Exception as e:
        elapsed = time.time() - start_time
        logger.warning("Docker get_container_details failed: %s (took %.2fs)", e, elapsed)
        return []


def get_image_details() -> list[dict[str, Any]]:
    """Get detailed image info for display. Returns list of {id, tags, size_bytes, created}.
    
    Fetches additional fields not included in list_images() for UI display purposes.
    """
    start_time = time.time()
    try:
        import docker
        client = docker.from_env()
        try:
            images = client.images.list()
            result = []
            for img in images:
                attrs = img.attrs
                result.append({
                    "id": img.id,
                    "short_id": img.short_id,
                    "tags": attrs.get("RepoTags") or [],
                    "size_bytes": attrs.get("Size") or 0,
                    "created": attrs.get("Created"),
                })
            elapsed = time.time() - start_time
            logger.debug("Docker get_image_details: total=%.2fs (count=%d)", elapsed, len(result))
            return result
        finally:
            client.close()
    except Exception as e:
        elapsed = time.time() - start_time
        logger.warning("Docker get_image_details failed: %s (took %.2fs)", e, elapsed)
        return []


def get_container_volume_mounts() -> dict[str, list[dict[str, Any]]]:
    """Get volume mounts for all containers. Returns {volume_name: [{container_id, container_created}, ...]}.
    
    Only includes mounts of type 'volume' (not bind mounts).
    Used for volume attribution: first container (by creation time) that mounts a volume owns it.
    """
    start_time = time.time()
    try:
        import docker
        client = docker.from_env()
        try:
            containers = client.containers.list(all=True)
            volume_to_containers: dict[str, list[dict[str, Any]]] = {}
            for c in containers:
                mounts = c.attrs.get("Mounts") or []
                created = c.attrs.get("Created")
                created_ts = _parse_created_iso(created)
                for mount in mounts:
                    if mount.get("Type") != "volume":
                        continue
                    vol_name = mount.get("Name")
                    if not vol_name:
                        continue
                    if vol_name not in volume_to_containers:
                        volume_to_containers[vol_name] = []
                    volume_to_containers[vol_name].append({
                        "container_id": c.id,
                        "container_created": created_ts,
                    })
            # Sort each volume's containers by creation time (oldest first)
            for vol_name in volume_to_containers:
                volume_to_containers[vol_name].sort(key=lambda x: x["container_created"])
            elapsed = time.time() - start_time
            logger.debug(
                "Docker get_container_volume_mounts: total=%.2fs (containers=%d, volumes_with_mounts=%d)",
                elapsed, len(containers), len(volume_to_containers)
            )
            return volume_to_containers
        finally:
            client.close()
    except Exception as e:
        elapsed = time.time() - start_time
        logger.warning("Docker get container volume mounts failed: %s (took %.2fs)", e, elapsed)
        return {}


def docker_inspect(kind: str, object_id: str) -> dict[str, Any]:
    """Return full `docker inspect` JSON dict for a container, image, or volume.

    `kind` is ``container``, ``image``, or ``volume``. `object_id` is container id,
    image id (e.g. sha256:...), or volume name.

    Raises:
        docker.errors.NotFound: object does not exist.
        ValueError: invalid kind.
    """
    from docker.errors import NotFound

    k = (kind or "").strip().lower()
    if k not in {"container", "image", "volume"}:
        raise ValueError(f"invalid kind: {kind!r}")

    start_time = time.time()
    try:
        import docker

        client = docker.from_env()
        try:
            api = client.api
            if k == "container":
                data = api.inspect_container(object_id)
            elif k == "image":
                data = api.inspect_image(object_id)
            else:
                data = api.inspect_volume(object_id)
            elapsed = time.time() - start_time
            logger.debug("docker_inspect kind=%s id=%s… in %.2fs", k, object_id[:16], elapsed)
            return data
        finally:
            client.close()
    except NotFound:
        raise
    except Exception as e:
        elapsed = time.time() - start_time
        logger.warning("docker_inspect kind=%s failed: %s (took %.2fs)", k, e, elapsed)
        raise
