"""Docker API/CLI client for listing containers, images, and disk usage (slave).

Note on timeouts: Docker API requests can take ~1 minute to complete. The collect_events_since()
function has a configurable timeout (default 90s). Other Docker SDK calls (list_containers,
get_system_df, etc.) use the SDK's default timeout (no timeout by default, waits indefinitely).
If you need explicit timeouts for all Docker operations, configure the Docker client with
timeout parameters when creating it.
"""

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


def list_containers(all_containers: bool = True) -> list[dict[str, Any]]:
    """List containers (running and stopped). Returns list of {id, name, image_id, created, labels}."""
    try:
        import docker
        client = docker.from_env()
        try:
            containers = client.containers.list(all=all_containers)
            return [
                {
                    "id": c.id,
                    "short_id": c.short_id,
                    "name": (c.name or ""),
                    "image": (c.image.id if c.image else None),
                    "created": c.attrs.get("Created"),
                    "labels": c.attrs.get("Labels") or {},
                }
                for c in containers
            ]
        finally:
            client.close()
    except Exception as e:
        logger.warning("Docker list containers failed: %s", e)
        return []


def list_images() -> list[dict[str, Any]]:
    """List images. Returns list of {id, short_id, size, created}."""
    try:
        import docker
        client = docker.from_env()
        try:
            images = client.images.list()
            return [
                {
                    "id": img.id,
                    "short_id": img.short_id,
                    "size": img.attrs.get("Size") or 0,
                    "created": img.attrs.get("Created"),
                }
                for img in images
            ]
        finally:
            client.close()
    except Exception as e:
        logger.warning("Docker list images failed: %s", e)
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


def get_system_df() -> dict[str, Any]:
    """Run 'docker system df -v' equivalent: per-container and per-image sizes. Returns dict with Containers, Images."""
    try:
        import docker
        client = docker.from_env()
        try:
            # Docker SDK doesn't expose "system df -v" directly; build from containers + images
            containers = client.containers.list(all=True)
            images = client.images.list()
            # Size of a container = size of its writable layer (from inspect)
            container_sizes: dict[str, int] = {}
            for c in containers:
                try:
                    inspect = client.api.inspect_container(c.id, size=True)
                    size_rw = inspect.get("SizeRw") or 0
                    container_sizes[c.id] = size_rw
                except Exception:
                    container_sizes[c.id] = 0
            image_sizes = {img.id: (img.attrs.get("Size") or 0) for img in images}
            return {
                "containers": container_sizes,
                "images": image_sizes,
            }
        finally:
            client.close()
    except Exception as e:
        logger.warning("Docker system df failed: %s", e)
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
    try:
        import docker
        client = docker.from_env()
        try:
            # Get layer IDs (oldest first)
            inspect = client.api.inspect_image(image_id)
            rootfs = inspect.get("RootFS", {})
            layer_ids = rootfs.get("Layers", [])
            if not layer_ids:
                return []
            # Get layer sizes from history (newest first, so reverse)
            history = client.api.history(image_id)
            # history returns list of dicts with 'Size' field (incremental size added by each layer)
            # Match layers: RootFS.Layers[0] (oldest) -> history[-1] (oldest), RootFS.Layers[-1] (newest) -> history[0] (newest)
            history_sizes = [h.get("Size", 0) for h in reversed(history)]  # Reverse to oldest first
            # Match layer_ids with sizes (pad if mismatch)
            result: list[tuple[str, int]] = []
            for i, layer_id in enumerate(layer_ids):
                size = history_sizes[i] if i < len(history_sizes) else 0
                result.append((layer_id, size))
            return result
        finally:
            client.close()
    except Exception as e:
        logger.warning("Docker get image layers failed for %s: %s", image_id[:12], e)
        return []
