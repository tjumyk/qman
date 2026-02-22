# Docker volume disk usage in quota control – design

This note outlines how to **include Docker volume disk usage** in the existing Docker quota model (containers + image layers), so that total Docker usage and per-user usage reflect volumes as well.

---

## Status: IMPLEMENTED

Volume quota support has been implemented. See the Implementation section below for details.

---

## Current behaviour

- **Counted:** container writable layer size (`SizeRw`) + image layer sizes (first-creator attribution) + **volume sizes**.
- **Source:** `get_system_df(include_volumes=True)` builds container/image/volume sizes from the Docker API.

---

## Why include volumes

- Volumes can be a large part of Docker disk usage (databases, caches, uploads).
- Ignoring them under-reports usage and can make quota enforcement misleading (e.g. user under quota by container+image but over in reality because of volumes).

---

## Data source for volume sizes

- **Docker Engine API:** `GET /system/df` (in Python: `client.api.df()`) returns a **`Volumes`** list.
- Each entry has: `Name`, `Mountpoint`, `UsageData.Size` (bytes), `UsageData.RefCount`, `CreatedAt`, `Labels`.
- No extra subprocess or host filesystem access is needed; the daemon reports size.

---

## Attribution: who "owns" a volume

Volume attribution is **persisted** in the `docker_volume_attribution` table. Attribution priority:

1. **`qman.user` label** on the volume (source='label') – explicit owner, highest priority, can change ownership
2. **Existing attribution in DB** – preserved even if the original container is removed (supports dangling volumes)
3. **First container (by creation time)** that mounts it (source='container') – initial attribution for new volumes
4. **Unattributed** – volume not stored in DB, counted in `unattributed_bytes`

This ensures:
- A user who creates a volume and later removes the container still owns the volume
- Labels can override/change ownership at any time
- Dangling volumes retain their original owner

---

## Persistence

Volume attribution is persisted in the `docker_volume_attribution` table:

```sql
CREATE TABLE docker_volume_attribution (
    volume_name VARCHAR(255) PRIMARY KEY,
    host_user_name VARCHAR(255) NOT NULL,
    uid INTEGER,
    size_bytes INTEGER DEFAULT 0,
    attribution_source VARCHAR(32) DEFAULT 'container',  -- 'label' or 'container'
    first_seen_at DATETIME
);
```

Reconciliation removes attributions for volumes that no longer exist in Docker.

---

## Implementation

### Files modified

| File | Changes |
|------|---------|
| `app/models_db.py` | Added `DockerVolumeAttribution` model |
| `app/docker_quota/docker_client.py` | Extended `get_system_df(include_volumes=True)` to fetch volume data; added `get_container_volume_mounts()` |
| `app/docker_quota/attribution_store.py` | Added volume CRUD: `get_volume_attributions()`, `get_volume_attribution()`, `set_volume_attribution()`, `update_volume_size()`, `delete_volume_attribution()` |
| `app/docker_quota/attribution_sync.py` | Added `sync_volume_attributions()` with label and container-based attribution |
| `app/docker_quota/quota.py` | Added `_reconcile_volume_attributions()`; updated `_aggregate_usage_by_uid()` to include volume usage |
| `alembic/versions/e3f5a7b9c812_*.py` | Migration for `docker_volume_attribution` table |

### Data flow

1. **Sync** (`sync_volume_attributions()` in Celery task):
   - Fetch volumes from Docker API with sizes and labels
   - For each volume: check label → check existing DB attribution → check first container mount
   - Persist attribution in `docker_volume_attribution`
   - Reconcile: remove attributions for deleted volumes

2. **Aggregation** (`_aggregate_usage_by_uid()`):
   - Fetch volume data with `get_system_df(include_volumes=True)`
   - Fetch volume attributions from DB
   - Add volume sizes to per-uid usage and total_used
   - Unattributed volumes count in `unattributed_bytes`

### Enforcement

- Current enforcement: remove containers when over quota
- Volume usage is part of the user's total Docker usage
- Volumes are **NOT** automatically deleted (data loss risk)
- Users must manually remove or prune volumes to free space

---

## Edge cases

- **Anonymous volumes:** Have generated names (long hash). Attributed the same way: first container that uses them.
- **Shared volumes:** Multiple containers using one volume. Attributed to first container's owner (by creation time). No double-counting.
- **Dangling volumes:** Keep their original owner attribution. If never attributed, count as unattributed.
- **Bind mounts:** Not included (not Docker volumes, covered by filesystem quota if applicable).
- **Volume removed:** Reconciliation removes the attribution row.

---

## Usage

### Set explicit volume owner via label

When creating a volume with Docker Compose:

```yaml
volumes:
  my_data:
    labels:
      qman.user: alice
```

Or with Docker CLI:

```bash
docker volume create --label qman.user=alice my_data
```

### Apply migration

```bash
alembic upgrade head
```

The sync task will automatically start attributing volumes on the next run.
