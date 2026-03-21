---
name: docker-review-attribution
overview: Persist parsed Docker/audit events for admin review and add an admin-only UI/API to manually assign Docker entity attribution. Manual overrides are stored separately; manual has higher priority when resolving effective attribution for quota/enforcement.
todos:
  - id: design-db-review-events
    content: Add new ORM models + alembic migration(s) for persisted Docker/audit events used by admin review (include entity association, fingerprint uniqueness, and review status).
    status: completed
  - id: design-db-manual-overrides
    content: Add ORM models + migration for manual attribution override tables (container, image, layer, volume); preserve existing auto-attribution tables unchanged.
    status: completed
  - id: persist-events-in-sync
    content: Update `app/docker_quota/attribution_sync.py` to persist audit/docker events, mark `used_for_auto_attribution`, and reconcile override tables (delete overrides for entities no longer in Docker).
    status: completed
  - id: effective-attribution-store
    content: Add override CRUD in attribution_store; add effective-attribution resolution (manual wins over auto) and use it in quota.py and enforcement for all entity types; implement cascade when setting manual overrides.
    status: completed
  - id: slave-review-endpoints
    content: Add admin (API-key) slave endpoints in `app/routes/remote_api.py` to fetch review queue, fetch entity events, and apply manual attribution (write to override tables) with cascade.
    status: completed
  - id: master-admin-proxy
    content: Add admin (oauth) master endpoints in `app/routes/api.py` that proxy to the slave endpoints and resolve `oauth_user_id` -> `{host_user_name, uid}`.
    status: pending
  - id: frontend-admin-ui
    content: Create `frontend/src/pages/AdminDockerUsageReviewPage.tsx`, wire it into `frontend/src/App.tsx` nav/routes, and add API client + zod schemas for queue/events/assign flows.
    status: pending
  - id: sanity-checks
    content: Run lint/type checks and add minimal backend smoke tests for effective-attribution resolution and manual override cascade.
    status: pending
isProject: false
---

## Goal

Admin can (a) inspect all parsed Docker/audit usage information tied to containers/images/volumes, and (b) manually assign container/image/volume ownership to a user. **Manual assignments are stored in separate override tables; auto-attribution data is preserved.** When resolving attribution for quota computation, enforcement, and UI, **manual override has higher priority**; if no override exists, auto attribution is used. Manual assignment can cascade (container -> image -> layers; container mounts -> volumes; image -> layers) by writing override rows for the related entities.

## Architecture (master<->slave)

- Existing docker attribution tables live on the *slave* side (see `app/docker_quota/attribution_store.py` + ORM models in `app/models_db.py`), while the React UI runs on the *master*.
- Therefore, new admin operations will be implemented as:
  - Slave: secure read/write endpoints under `app/routes/remote_api.py` (`/remote-api/...`) guarded by `requires_api_key`.
  - Master: admin UI endpoints under `app/routes/api.py` guarded by `@oauth.requires_admin`, which proxy to the slave endpoints and resolve `oauth_user_id` -> `host_user_name` + `uid`.

```mermaid
flowchart LR
  AdminUI[Admin React UI] -->|OAuth session| MasterAPI[Master /api/admin/...]
  MasterAPI -->|API key| SlaveRemote[Slave /remote-api/...]
  SlaveRemote --> DB[(Slave DB: docker_* attribution + override + review tables)]
  SlaveRemote --> SlaveDocker[Docker helpers (mounts/layers resolution)]
```



## Data model changes (slave DB)

### 1) Persist parsed events for review

Add new ORM models + alembic migration(s) in the slave DB:

- `DockerUsageAuditEvent` (parsed from `parse_audit_logs`)
- `DockerUsageDockerEvent` (collected from `collect_events_since`)

Each record should include:

- `source` (audit/docker)
- `event_ts` / `created_at`
- Docker/audit identifiers for linking:
  - container_id (when found)
  - image_id (when resolved)
  - image_ref (name:tag when resolved_id fails)
  - volume_name (when found)
- resolved user info from matching heuristics:
  - `uid` (numeric when resolvable)
  - `host_user_name` (passwd-resolved)
- the raw parsed payload (store JSON in `Text` for SQLite compatibility)
- review status fields:
  - `used_for_auto_attribution` (bool; set when auto attribution consumed an event)
  - `manual_resolved_at`, `manual_resolved_by_oauth_user_id` (nullable)

Also add a small "fingerprint" / unique constraint so repeated sync runs do not create duplicates (based on timestamp + type/action/id + key/subcommand + short hash of payload).

### 2) Manual attribution overrides (separate tables, higher priority)

Add new ORM models + migration for **override** tables (auto-attribution tables remain unchanged):

- `DockerContainerAttributionOverride` (container_id PK, host_user_name, uid, created_at, resolved_by_oauth_user_id)
- `DockerImageAttributionOverride` (image_id PK, puller_host_user_name, puller_uid, created_at, resolved_by_oauth_user_id)
- `DockerLayerAttributionOverride` (layer_id PK, first_puller_host_user_name, first_puller_uid, created_at, resolved_by_oauth_user_id)
- `DockerVolumeAttributionOverride` (volume_name PK, host_user_name, uid, created_at, resolved_by_oauth_user_id)

**Effective attribution resolution:** All code that currently reads from the existing attribution tables (e.g. `get_container_attributions`, `get_image_attributions`, `get_layer_attributions`, `get_volume_attributions`) must be updated to return **effective** attribution: if an override row exists for that entity, use it; otherwise use the existing auto row. Quota aggregation (`_aggregate_usage_by_uid` in `quota.py`), enforcement (`docker_quota_tasks`), and remote-api detail endpoints must use this effective resolution so manual has higher priority everywhere.

## Sync changes (slave)

Update `app/docker_quota/attribution_sync.py` so it:

1. Persists all parsed audit events from `parse_audit_logs(...)` into the new audit event table.
2. Persists all collected docker events from `collect_events_since(...)` into the new docker event table.
3. When auto-attribution logic sets attributions, it marks the corresponding persisted events as `used_for_auto_attribution=true`.

Changes are primarily in:

- `sync_containers_from_audit()` (audit -> container attribution)
- `sync_from_docker_events()` (docker events -> container/image attribution, plus container start -> volume last-mounted updates)

**Reconciliation of override tables:** When existing sync logic removes auto-attribution rows for entities that no longer exist in Docker (e.g. `_reconcile`_* in quota.py), also delete the corresponding override rows for that entity so we do not keep stale manual overrides (e.g. container/image/volume/layer removed from Docker -> delete override if present).

## Manual attribution endpoints (slave)

Add admin-only (API-key) endpoints in `app/routes/remote_api.py`:

1. `GET /remote-api/docker/usage/review-queue`
  - Query params: `entity_type` (container|image|volume), `cursor/page`
  - Returns entity list with current attribution and the count of associated events that are not manually resolved.
2. `GET /remote-api/docker/usage/events`
  - Query params: `entity_type` + `entity_id` or `volume_name` + optional `include_used`
  - Returns ordered event list (audit+docker) for that entity.
3. `POST /remote-api/docker/usage/attribute` — set manual override (body: `entity_type`, `container_id`|`image_id`|`volume_name`, `host_user_name`, `uid`, `cascade`, `manual_resolver` optional).
4. `DELETE /remote-api/docker/usage/attribute` — clear manual override for an entity (query: `entity_type`, `entity_id` or `volume_name`; optional `cascade=true` to clear related overrides).

Implement cascade by **writing override rows only** (auto-attribution tables are not modified):

- container manual attribution: insert/update override for container_id; resolve image_id and volumes from Docker; insert/update overrides for that image, its layers, and mounted volumes.
- image manual attribution: insert/update override for image_id; insert/update overrides for all layers of that image.
- volume manual attribution: insert/update override for volume_name.

Also set `manual_resolved`_* fields on persisted events tied to the affected entity so the UI queue shrinks.

## Manual attribution endpoints (master)

In `app/routes/api.py` add admin endpoints (oauth admin required) that proxy to the slave endpoints:

1. `GET /api/admin/docker/usage/review-queue?host_id=...&entity_type=...`
2. `GET /api/admin/docker/usage/events?host_id=...&entity_type=...&entity_id=...`
3. `POST /api/admin/docker/usage/attribute?host_id=...` (body includes `oauth_user_id` + entity key)
4. `DELETE /api/admin/docker/usage/attribute?host_id=...&entity_type=...&entity_id=...` (proxy to slave to clear override)

Master responsibilities:

- Resolve `oauth_user_id` -> `host_user_name` via `OAuthHostUserMapping`.
- Resolve `host_user_name` -> `uid` via slave's existing `GET /remote-api/users/resolve` (proxy already exists at `/api/quotas/<slave_id>/users/resolve` in `app/routes/api.py`).
- Proxy the final `{host_user_name, uid}` to the slave manual attribution endpoint.

## Attribution store changes (slave)

Update `app/docker_quota/attribution_store.py`:

- **Override CRUD:** Add functions to get/set/delete rows in the four override tables (e.g. `get_container_attribution_override`, `set_container_attribution_override`; same pattern for image, layer, volume). Cascade helper: when setting a manual override for a container, call Docker helpers to get image_id and mounted volume names, then set overrides for image, all its layers, and those volumes.
- **Effective attribution:** Change `get_container_attributions`, `get_image_attributions`, `get_layer_attributions`, `get_volume_attributions` (or add wrappers used by quota/API) so they return **effective** attribution: for each entity, if an override exists use it, else use the existing auto row. All quota aggregation (`quota.py`), enforcement (`docker_quota_tasks`), and remote-api detail responses must use these effective getters so manual has higher priority everywhere.

## Frontend UI

Add a new admin route + page:

- Route: `/manage/docker-usage-review`
- Page component: `frontend/src/pages/AdminDockerUsageReviewPage.tsx`

UI behavior:

- Select `host` (existing `fetchHosts()` can be reused).
- Filter entity type (container|image|volume).
- Display review queue of entities.
- Selecting an entity opens a detail drawer/modal showing:
  - current attribution (host_user_name/uid)
  - associated audit/docker events (sortable)
  - resolved user info if mapping exists
- Attribution action:
  - OAuth user dropdown filtered to those mapped for the selected host (from existing `fetchAdminMappings`).
  - "Assign" button triggers `POST /api/admin/docker/usage/attribute` (writes manual override; effective attribution updates immediately).
  - "Clear manual assignment" (when entity has an override) triggers `DELETE /api/admin/docker/usage/attribute` to remove override and fall back to auto attribution.
  - On success: invalidate React Query cache for the queue.

Update app shell nav to include the new entry when `me.is_admin`.

## Concrete file touchpoints

Backend:

- `[slave DB]` `app/models_db.py` (new ORM models: review events + override tables)
- `[slave DB]` `alembic/versions/`* (new migrations)
- `app/docker_quota/attribution_sync.py` (persist parsed events + mark used)
- `app/docker_quota/attribution_store.py` (override CRUD, effective-attribution resolution, cascade)
- `app/docker_quota/quota.py` (use effective attribution for aggregation)
- `app/routes/remote_api.py` (review queue/events/attribute endpoints)
- `app/routes/api.py` (master admin proxies)

Frontend:

- `frontend/src/App.tsx` (add nav + route)
- `frontend/src/pages/AdminDockerUsageReviewPage.tsx` (new)
- `frontend/src/api/index.ts` (new admin API client functions)
- `frontend/src/api/schemas.ts` (new zod schemas)

## Mermaid: UI workflow

```mermaid
flowchart TD
  SelectHost[Select host] --> SelectEntityType[Select entity type]
  SelectEntityType --> EntityQueue[Review queue]
  EntityQueue --> EntityDetail[Entity detail + events]
  EntityDetail --> PickUser[Pick mapped OAuth user]
  PickUser --> Assign[Assign (override + cascade)]
  Assign --> Refresh[Refresh queue]
```



## Assumptions

- Auto-attribution data is preserved; manual assignments are stored in separate override tables. Effective attribution for quota/enforcement/UI is: override if present, else auto.
- Manual cascade writes override rows for related entities (container -> image + layers + mounted volumes; image -> layers).
- Slave DB is per-host (docker attribution tables do not include `host_id`), so master must proxy to the slave.
- Events that cannot be linked to any container/image/volume will be stored but ignored by the UI.

