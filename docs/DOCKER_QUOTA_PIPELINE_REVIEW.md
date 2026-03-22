# Docker Quota Pipeline - Comprehensive Review

## Status: ✅ FULLY IMPLEMENTED (Core Pipeline + Image Layer Quota)

**Last Updated**: 2026-02-18

---

## ✅ IMPLEMENTED (Core Pipeline + Image Layer Quota)

### 1. Database Models & Migration
- ✅ `DockerContainerAttribution` table (container_id → user)
- ✅ `DockerImageAttribution` table (image_id → puller) 
- ✅ `DockerUserQuotaLimit` table (uid → block_hard_limit)
- ✅ `DockerLayerAttribution` table (layer_id → first creator) **NEW**
- ✅ Alembic migration `c9e4d2f3a601_add_docker_quota_tables.py`
- ✅ Alembic migration `d2026759b218_add_docker_layer_attribution_table.py` **NEW**

### 2. Attribution Store (`app/docker_quota/attribution_store.py`)
- ✅ `get_container_attributions()` - list all container attributions
- ✅ `set_container_attribution()` - upsert container attribution
- ✅ `delete_container_attribution()` - remove attribution
- ✅ `get_user_quota_limit()` / `set_user_quota_limit()` - quota limits
- ✅ `get_all_user_quota_limits()` - all limits
- ✅ `get_image_attributions()` - list all image attributions **NEW**
- ✅ `set_image_attribution()` - image puller attribution
- ✅ `get_layer_attributions()` - list all layer attributions **NEW**
- ✅ `set_layer_attribution()` - upsert layer attribution (first creator wins) **NEW**
- ✅ `get_layers_for_image()` - get layer IDs for an image **NEW**
- ✅ `attribute_image_layers()` - extract and attribute NEW layers to creator **NEW**

### 3. Docker Client (`app/docker_quota/docker_client.py`)
- ✅ `get_docker_data_root()` - discover Docker data root
- ✅ `list_containers()` - list all containers
- ✅ `list_images()` - list all images
- ✅ `get_system_df()` - container/image sizes
- ✅ `stop_container()` / `remove_container()` - enforcement actions
- ✅ `collect_events_since()` - non-blocking Docker events collection
- ✅ `_parse_created_iso()` - timestamp parsing
- ✅ `get_image_layers_with_sizes()` - extract layers and sizes from image **NEW**

### 4. Audit Parser (`app/docker_quota/audit_parser.py`)
- ✅ `parse_audit_logs()` - parse auditd logs with keys `docker-socket`, `docker-client`
- ✅ Handles multiple timestamp formats (Unix float, date strings)
- ✅ Default keys: `docker-socket`, `docker-client`

### 5. Attribution Sync (`app/docker_quota/attribution_sync.py`)
- ✅ `sync_containers_from_audit()` - correlate containers with audit events
  - ✅ Updates container sizes during sync **NEW**
- ✅ `sync_from_docker_events()` - track all image creation events **UPDATED**
  - ✅ Container `create` events
  - ✅ Container `commit` events (creates new image) **NEW**
  - ✅ Image `pull` events (with layer extraction) **UPDATED**
  - ✅ Image `tag` events (for new images from builds) **NEW**
  - ✅ Image `import` events **NEW**
  - ✅ Image `load` events **NEW**
  - ✅ Updates container/image sizes during sync **NEW**
  - ✅ Extracts and attributes layers for all image events **NEW**
- ✅ `sync_existing_images()` - backfill layers for existing images **NEW**
- ✅ Time-window correlation (120 seconds)
- ✅ `run_sync_docker_attribution()` - orchestrates all sync methods **UPDATED**

### 6. Quota Computation (`app/docker_quota/quota.py`)
- ✅ `_aggregate_usage_by_uid()` - aggregates container + image layer usage per user **UPDATED**
  - ✅ Container usage: sum of writable layer sizes
  - ✅ Image layer usage: sum of layer sizes where user is first creator **NEW**
  - ✅ Total usage = container usage + image layer usage **NEW**
- ✅ `get_devices()` - returns virtual Docker device
- ✅ `collect_remote_quotas()` - device + user quotas list
- ✅ `collect_remote_quotas_for_uid()` - per-user device
- ✅ `set_user_quota()` - set quota limit
- ✅ Handles `DOCKER_QUOTA_RESERVED_BYTES` semantics correctly
- ✅ Handles unattributed usage (containers + image layers) **UPDATED**
- ✅ Unit consistency: `block_current` in bytes, `block_hard_limit` in 1K blocks (consistent with usrquota)

### 7. Celery Tasks (`app/tasks/docker_quota_tasks.py`)
- ✅ `enforce_docker_quota()` - stops/removes containers when over quota **UPDATED**
  - ✅ Checks container + image layer usage (not just containers) **NEW**
  - ✅ Recomputes total usage after each container removal **NEW**
- ✅ Configurable enforcement order (`newest_first`, `oldest_first`, `largest_first`)
- ✅ `sync_docker_attribution()` - periodic attribution sync
- ✅ Event posting to master
- ✅ Config loading from `CONFIG_PATH` or env vars

### 8. Celery App (`app/celery_app.py`)
- ✅ Celery app configuration
- ✅ Beat schedule for enforcement (default 300s) and sync (120s)
- ✅ Task routing to `qman.docker` queue
- ✅ Configurable intervals

### 9. Remote API Integration (`app/routes/remote_api.py`)
- ✅ Merges Docker device into quota results
- ✅ Handles `device=docker` in `PUT /remote-api/quotas/users/<uid>`
- ✅ Calls `docker_set_user_quota()` correctly

### 10. Master API (`app/routes/api.py`)
- ✅ `POST /api/internal/slave-events` endpoint
- ✅ Authenticated with `X-API-Key` header
- ✅ Calls `process_slave_events()` for notifications

### 11. Notifications (`app/notifications.py`)
- ✅ `send_email()` - SMTP email sending
- ✅ Supports port 465 (implicit SSL) and 587 (STARTTLS)
- ✅ `resolve_oauth_user_id()` - host_user_name → oauth_user_id
- ✅ `get_email_for_oauth_user()` - oauth_user_id → email (with token support)
- ✅ `process_slave_events()` - processes Docker quota events (e.g. quota exceeded, container stopped; legacy container_removed)
- ✅ INFO logging when skipping due to missing OAuth mapping

### 12. Configuration (`app/models.py`, `app/__init__.py`)
- ✅ `AppConfig` includes all Docker/Celery/Notification config keys
- ✅ Validation: at least one quota backend must be enabled
- ✅ `make_celery()` called when `USE_DOCKER_QUOTA` is enabled
- ✅ All config keys loaded correctly

### 13. Auditd Rules (`deploy/auditd-docker-quota.rules`)
- ✅ Rules for `docker-socket` and `docker-client` keys
- ✅ Installation instructions in comments

### 14. Frontend Integration
- ✅ `DeviceUsage` component handles usage breakdown (tracked vs other)
- ✅ `deviceTypeDocker` i18n strings
- ✅ `containerRemovedDueToQuota` i18n strings
- ✅ Frontend displays Docker device correctly
- ✅ Simplified: backend `used` now includes attributed + unattributed (consistent with pyquota/ZFS)

---

## ✅ IMPLEMENTATION DETAILS

### Image Layer Quota Implementation

**Layer Attribution Model**:
- Each layer is attributed to the **first creator** (first puller/builder/committer/importer/loader)
- Once attributed, layers stay attributed even if others use them
- Layers are extracted using Docker API's `inspect_image()` and `history()`
- Layer sizes are incremental (from `history()` API)

**Image Creation Methods Supported**:
1. **Pull**: `docker pull` → layers attributed to puller
2. **Build**: `docker build` → tracked via `tag` events, layers attributed to builder
3. **Commit**: `docker commit` → tracked via container `commit` events, new layer attributed to committer
4. **Import**: `docker import` → layers attributed to importer
5. **Load**: `docker load` → layers attributed to loader

**Quota Computation**:
- User's total usage = container writable layers + image layers (where user is first creator)
- Device total = sum of all container sizes + sum of all image sizes
- Device used = attributed + unattributed (consistent with pyquota/ZFS: `used + free = total`)
- Unattributed = total - sum of attributed usage (containers + layers)

**Enforcement**:
- Checks `container_used + image_layer_used` against quota limit
- Stops at most one running attributed container per user per beat (containers are not removed; image layers are never auto-removed)

**Size Updates**:
- Container sizes updated during `sync_containers_from_audit()` and `sync_from_docker_events()`
- Image sizes updated during `sync_from_docker_events()` and `sync_existing_images()`
- Ensures attribution store has accurate size information

---

## 🔍 KNOWN LIMITATIONS & NOTES

### 1. **Commit Event Image ID**
**Location**: `app/docker_quota/attribution_sync.py:255`
**Issue**: Docker commit events may not include the new image ID directly in the event payload.
**Current Behavior**: Tries to attribute via container owner or audit correlation.
**Impact**: Some committed images may not be attributed immediately (will be caught by `sync_existing_images()`).
**Status**: Acceptable workaround; may need refinement based on actual Docker event structure.

### 2. **Layer Attribution Granularity**
**Note**: Layers are attributed at the layer level, not image level. This means:
- If image A has layers [L1, L2, L3] and image B has layers [L1, L2, L4], layers L1 and L2 are only counted once (attributed to first creator).
- This correctly reflects actual disk usage (layers are shared on disk).

### 3. **Enforcement Stops Containers; Usage May Stay Over Limit**
**Note**: Enforcement stops containers (does not `docker rm`). Stopping does not reduce attributed usage from existing writable layers or shared image layers.
**Impact**: If a user exceeds quota due to image layers or many stopped containers, they must manually prune images/containers or ask an admin for a higher quota.
**Future Consideration**: Optional AuthZ or other daemon-level blocks on new creates; automatic image removal remains risky because of shared layers.

### 4. **Backfill for Existing Images**
**Note**: `sync_existing_images()` backfills layers for images that existed before layer attribution was implemented.
**Behavior**: Runs as part of `run_sync_docker_attribution()`, processes all images in `DockerImageAttribution`.
**Impact**: Existing images will gradually get their layers attributed on subsequent sync runs.

---

## ✅ RESOLVED ISSUES

### 1. ✅ Image Layer Quota Implemented
**Status**: **FIXED**
- Layer attribution model and migration added
- Layer extraction function implemented
- Layer attribution logic implemented
- Image usage included in quota computation
- Enforcement checks container + image usage

### 2. ✅ Attribution Sync Handles All Image Events
**Status**: **FIXED**
- Build events handled (via `tag` events for new images)
- Commit events handled (container `commit` → new image)
- Import/load events handled
- Tag events handled (for new image references)

### 3. ✅ Container/Image Size Updates
**Status**: **FIXED**
- Container sizes updated during sync
- Image sizes updated during sync
- Attribution store now has accurate size information

### 4. ✅ Unit Consistency
**Status**: **CONFIRMED**
- `block_current` in bytes (consistent with usrquota)
- `block_hard_limit` in 1K blocks (consistent with usrquota)
- No changes needed

---

## 📋 SUMMARY CHECKLIST

### Core Pipeline ✅
- [x] Database models and migration
- [x] Attribution store (containers, images, quotas)
- [x] Docker client functions
- [x] Audit parser
- [x] Attribution sync (containers + all image events)
- [x] Quota computation (containers + image layers)
- [x] Celery enforcement (container + image usage)
- [x] Remote API integration
- [x] Master API (slave events)
- [x] Email notifications
- [x] Configuration
- [x] Frontend integration

### Image Layer Quota ✅
- [x] Layer attribution model and migration
- [x] Layer extraction from Docker API
- [x] Layer attribution logic
- [x] Image usage in quota computation
- [x] Build/commit/import/load/tag event handling
- [x] Enforcement including image layers
- [x] Size updates during sync
- [x] Backfill for existing images

### All Features Complete ✅
- [x] Container quota (writable layers)
- [x] Image layer quota (attributed to first creator)
- [x] All image creation methods (pull, build, commit, import, load)
- [x] Size updates during sync
- [x] Enforcement including both container and image usage
- [x] Unit consistency (bytes for current, 1K blocks for limits)

---

## 🎯 IMPLEMENTATION STATUS

**Status**: ✅ **FULLY IMPLEMENTED**

The Docker quota pipeline is **fully functional** with complete support for:
- ✅ Container quota (writable layers)
- ✅ Image layer quota (attributed to first creator)
- ✅ All image creation methods (pull, build, commit, import, load, tag)
- ✅ Size tracking and updates
- ✅ Quota enforcement (container + image usage)
- ✅ Email notifications
- ✅ Master-slave event communication

**Migration Required**: Run Alembic migration `d2026759b218_add_docker_layer_attribution_table.py` to add the layer attribution table.

**Testing Recommendations**:
1. Test layer extraction with various image types
2. Test attribution for build/commit/import/load events
3. Test quota enforcement with image layers
4. Test backfill for existing images
5. Verify unattributed usage calculation includes image layers

---

## 📚 Related Documentation

- **Design Document**: `docs/DOCKER_IMAGE_QUOTA_DESIGN.md` - Layer-level implementation plan and decisions
- **Attribution Details**: `docs/DOCKER_ATTRIBUTION_FROM_AUDIT_AND_EVENTS.md` - How attribution works
- **Review Decisions**: `docs/DOCKER_QUOTA_REVIEW.md` - Design decisions and resolutions
