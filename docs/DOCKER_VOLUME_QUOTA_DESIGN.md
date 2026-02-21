# Docker volume disk usage in quota control – design

This note outlines how to **include Docker volume disk usage** in the existing Docker quota model (containers + image layers), so that total Docker usage and per-user usage reflect volumes as well.

---

## Current behaviour

- **Counted today:** container writable layer size (`SizeRw`) + image layer sizes (first-creator attribution).
- **Not counted:** Docker named and anonymous volumes.
- **Source:** `get_system_df()` builds container/image sizes from the Docker API; volumes are not queried.

---

## Why include volumes

- Volumes can be a large part of Docker disk usage (databases, caches, uploads).
- Ignoring them under-reports usage and can make quota enforcement misleading (e.g. user under quota by container+image but over in reality because of volumes).

---

## Data source for volume sizes

- **Docker Engine API:** `GET /system/df` (in Python: `client.api.df()`) returns a **`Volumes`** list (and `VolumeUsage`).
- Each entry has: `Name`, `Mountpoint`, `UsageData.Size` (bytes), `UsageData.RefCount`, `CreatedAt`, `Labels`.
- No extra subprocess or host filesystem access is needed; the daemon reports size.

**Implementation:** Add a function (e.g. in `docker_client.py`) that calls `client.api.df()` and returns a dict `volume_name -> size_bytes` (and optionally the full volume list for attribution). Use this in the same code paths that today call `get_system_df()` so one API call can feed both container/image and volume data.

---

## Attribution: who “owns” a volume

Volumes can be:

1. **Named volumes** – created explicitly or by Compose; can be used by one or many containers.
2. **Anonymous volumes** – created with a container (e.g. `docker run -v /data`); typically one container.

Attribution options:

| Approach | Pros | Cons |
|----------|------|------|
| **A. Same as (first) using container** | Reuses existing container attribution; no new event parsing for volume create. | Need to resolve “first” or “primary” container when multiple use the volume. |
| **B. Volume create event + audit** | Can attribute at create time, like containers. | Volume create events; need to correlate with audit; anonymous volumes created with container. |
| **C. Label on volume** | Explicit owner (e.g. `qman.user=alice`). | Requires users/Compose to set labels; not set by default. |
| **D. First container (by creation time)** | Deterministic: first container that mounted it “owns” it. | Need to inspect container Mounts and creation time. |

**Recommendation:** **A + D combined**

- **Primary:** Attribute each volume to the **owner of the first container** that uses it (first by container creation time). Containers are already attributed (including audit/events); we have container ↔ volume from `inspect_container` Mounts and container creation time.
- **Fallback:** If a volume is not used by any container (dangling), treat as **unattributed** (count in total and in “unattributed”, not in any user’s usage). Optionally later: volume create event + audit to attribute at create time.
- **Optional:** If we later support volume labels (e.g. `qman.user`), they can override the “first container” rule.

So:

- **Per volume:** Get list of containers that mount this volume (from container inspect Mounts). Among them, take the one with earliest `Created`; get that container’s attribution (uid/host_user_name). That uid gets this volume’s `UsageData.Size` in their usage.
- **Unattributed:** Volume size is unattributed if no container uses it or no container using it has attribution.

---

## Persistence

- **Option 1 – No persistence:** Compute volume attribution on each run from current containers + current attributions. Simpler; no new tables; always consistent with current container list.
- **Option 2 – Persist volume attribution:** New table e.g. `docker_volume_attribution` (volume_name, host_user_name, uid, size_bytes, first_seen_at). Update on sync; reconcile when volume is removed (like layer cleanup). Allows attributing dangling volumes and faster aggregation.

**Recommendation:** Start with **Option 1** (compute from current containers + attributions). If we need to attribute dangling volumes or optimize, add Option 2 later.

---

## Where to plug in

1. **`docker_client.py`**
   - Add something like `get_volume_sizes()` that returns `dict[str, int]` (name → size) from `api.df()` (and optionally a list of volume infos with Name, Size, RefCount, CreatedAt for attribution).
   - Optionally extend `get_system_df()` to also return a `"volumes"` key (name → size), so a single “system df” concept includes containers, images, and volumes.

2. **`quota.py` – `_aggregate_usage_by_uid()`**
   - Take volume sizes (name → size).
   - Resolve volume → first container (by creation) → that container’s uid (from existing container attribution).
   - Add `total_volume_used` and per-uid volume usage; include in `total_used` and in `usage_by_uid`. Add volume share to `unattributed_bytes` when a volume has no attributed owner.

3. **`get_system_df()`**
   - Either call `api.df()` once and derive containers, images, and volumes from it, or keep building containers/images as today and add a separate call to get volume sizes. Prefer one `api.df()` call if the response includes everything we need (containers, images, volumes) to avoid extra round-trips.

4. **Enforcement**
   - Current enforcement: remove containers when over quota. Volume usage is already part of the user’s usage, so we still enforce by removing containers. We do **not** automatically delete volumes (data loss risk). Optionally: when reporting “over quota”, include a note that the user has volume usage and that removing containers may free container+image space but not volume space until they remove or prune volumes.

5. **Reconciliation**
   - If we persist volume attribution (Option 2): when a volume is removed from the daemon (e.g. `docker volume rm`), remove its row (like layer reconciliation). If we don’t persist, no reconciliation needed.

---

## Edge cases

- **Anonymous volumes:** Have generated names (long hash). Attributed the same way: first container that uses them (the creating container).
- **Shared volumes:** Multiple containers (same or different users) using one volume. We attribute the whole volume size to one owner (first container by creation). No double-counting: volume size is in total once and in one user’s usage.
- **Dangling volumes:** Not used by any container. Count in total Docker usage and in unattributed; no per-user usage.
- **Bind mounts:** Host paths mounted into containers are not Docker volumes; they are not stored under the Docker data root in the same way. We do **not** include them in Docker volume quota (they could be covered by existing filesystem/quota if applicable).

---

## Summary

- **Include volume sizes** in Docker quota: get them from `client.api.df()` and add to total and per-uid usage.
- **Attribution:** Volume → first container (by creation) that mounts it → that container’s attributed uid; if no such container or no attribution, count as unattributed.
- **Enforcement:** Unchanged (remove containers only); volume usage is part of the same quota number; optionally document that volume data is not removed by enforcement.
- **Implementation order:** (1) Get volume sizes from API and add to `get_system_df()` or a small helper; (2) In `_aggregate_usage_by_uid()`, resolve volume→container→uid and add volume usage to totals and per-uid; (3) Optionally persist volume attribution and reconcile removed volumes later.
