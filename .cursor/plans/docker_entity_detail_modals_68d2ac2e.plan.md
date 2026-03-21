---
name: Docker entity detail modals
overview: Add an admin-only detail modal on container/image/volume rows (Docker tabs) that loads docker inspect JSON, auto vs manual attribution breakdown, and persisted audit/docker usage events. This requires new slave inspect + attribution-breakdown endpoints, an extension to the existing events endpoint for resolved rows, master proxies under the existing `/api/quotas/:hostId/docker/...` pattern, and a shared React modal wired into the three tab components.
todos:
  - id: slave-inspect-attrib-events
    content: Add docker_inspect helper; remote routes inspect + attribution-detail; extend usage/events with include_resolved
    status: completed
  - id: master-proxy
    content: Proxy inspect + attribution-detail under /api/quotas/<slave_id>/docker/...
    status: completed
  - id: frontend-api-modal
    content: Schemas + API client; DockerEntityDetailModal (events table with explicit resolved/used badges); extend fetchAdminDockerUsageEvents
    status: completed
  - id: wire-tabs-i18n
    content: Add column + modal to ContainersTab, ImagesTab, VolumesTab; i18n (shared event status labels with AdminDockerUsageReviewPage if events table exists there)
    status: completed
isProject: false
---

# Docker entity detail modals (containers, images, volumes)

## Current gaps

- **Inspect**: Not exposed over HTTP. `[get_container_details](app/docker_quota/docker_client.py)` only returns a small summary for the list API, not full `docker inspect` JSON.
- **Manual override vs auto**: List APIs merge **effective** attribution only (`[remote_get_docker_containers](app/routes/remote_api.py)` uses `get_container_effective_attributions`). The UI cannot tell override vs auto without querying override tables + auto tables separately.
- **Events**: `[GET /remote-api/docker/usage/events](app/routes/remote_api.py)` always applies `manual_resolved_at.is_(None)`, so **manually resolved** audit/docker rows never appear. For a “full history” modal, add a query flag (e.g. `include_resolved=true`) to drop that filter when requested. Existing review UIs can keep default behavior.

Master already proxies Docker lists with `@oauth.requires_admin` as `[/api/quotas/<slave_id>/docker/containers|images|volumes](app/routes/api.py)`. Admin-only usage events exist as `[/api/admin/docker/usage/events](app/routes/api.py)` (forwards query params). The Docker tabs live under `[DockerDetailTabs](frontend/src/components/docker/DockerDetailTabs.tsx)` → `[ContainersTab](frontend/src/components/docker/ContainersTab.tsx)`, `[ImagesTab](frontend/src/components/docker/ImagesTab.tsx)`, `[VolumesTab](frontend/src/components/docker/VolumesTab.tsx)`.

## Backend (slave)

1. `**docker_client.py`**
  Add something like `docker_inspect(kind: Literal["container","image","volume"], object_id: str) -> dict[str, Any]` using `docker.APIClient.inspect_container` / `inspect_image` / `inspect_volume` (same socket as the rest of the slave). Map Docker 404 to a clear error for the route.
2. `**remote_api.py`**
  - `GET /remote-api/docker/inspect` with query `kind=container|image|volume` and `id=<container_id|image_id|volume_name>`, `@requires_api_key`, gated on `USE_DOCKER_QUOTA`. Response: `{"inspect": <dict>}`.  
  - `GET /remote-api/docker/usage/attribution-detail` (name flexible) with `entity_type` + `entity_id` or `volume_name`, returning JSON-serializable dicts, e.g. `{"auto": ..., "override": ...}` where each side is `null` or fields matching the override/auto models (datetimes as ISO). Implement by querying the existing ORM tables or thin wrappers in `[attribution_store.py](app/docker_quota/attribution_store.py)` (e.g. `get_container_attribution_breakdown(container_id)` mirroring existing `[get_container_attribution_override](app/docker_quota/attribution_store.py)` + auto row lookup).
3. **Extend** `GET /remote-api/docker/usage/events`
  - Add `include_resolved` (parse with existing `_parse_bool`). When true, **omit** the `manual_resolved_at.is_(None)` filter on both audit and docker event queries. Keep `include_used` behavior as today.

## Backend (master)

In `[api.py](app/routes/api.py)`, next to the existing Docker list proxies (~941–1017), add `@oauth.requires_admin` proxies:

- `GET /api/quotas/<slave_id>/docker/inspect?kind=...&id=...` → slave `/remote-api/docker/inspect`
- `GET /api/quotas/<slave_id>/docker/usage/attribution-detail?...` → slave new route

No change required to forward `include_resolved` for events if the frontend continues to call `**/api/admin/docker/usage/events`** (it already forwards arbitrary query params except `host_id`). Extend the frontend client to pass `include_resolved=true` (and `include_used=true` if you want the full event set).

## Frontend

1. `**api/schemas.ts` + `api/index.ts`**
  - Zod schemas: `inspect` as `z.record(z.string(), z.unknown())` (or loose passthrough), attribution-detail with nullable `auto`/`override` objects, reuse/extend existing `[dockerUsageReviewEventSchema](frontend/src/api/schemas.ts)` for events list.  
  - Functions: `fetchDockerInspect(hostId, { kind, id })`, `fetchDockerAttributionDetail(hostId, params)`, extend `fetchAdminDockerUsageEvents` with optional `includeResolved?: boolean`.
2. **Shared UI**
  New component e.g. `[frontend/src/components/docker/DockerEntityDetailModal.tsx](frontend/src/components/docker/DockerEntityDetailModal.tsx)`: Mantine `Modal` + `Tabs` (“Inspect”, “Attribution”, “Events”). On open, run **parallel** `useQueries` / `Promise.all` for the three endpoints; show per-section loading/error.  
  - **Inspect**: `JSON.stringify(inspect, null, 2)` in `ScrollArea` + monospace (project already has `@mantine/code-highlight` if you want syntax highlighting; optional).  
  - **Attribution**: show “Auto” and “Manual override” blocks; when override is null, state that quota uses auto only.  
  - **Events**: small table like `[AdminDockerUsageReviewPage](frontend/src/pages/AdminDockerUsageReviewPage.tsx)` (source, time, payload snippet); toggles optional for `include_used` / `include_resolved` defaulting to show full history (`include_resolved=true`, `include_used=true`).
  - **Event status columns (recommended)**: Surface `manual_resolved_at` and `used_for_auto_attribution` explicitly — not only inside `payload`. Use **two table columns** with **consistent, parallel naming** (same grammar and tone for both axes):
    - **Column headers** (stable nouns, not vague “Status”): e.g. **Review** and **Auto attribution** (or **Manual review** / **Auto attribution** if you need to disambiguate from other “review” copy).
    - **Label pairs** (one short word or two-word phrase per cell; use Mantine `Badge` + color: neutral/warning for “still open”, muted/default for “inactive”, green/teal for “done”):

      | Field                                                                                                                                                                                                                                                                                                                                                              | When false / null | When true / set |
      | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------- | --------------- |
      | `manual_resolved_at`                                                                                                                                                                                                                                                                                                                                               | **Pending**       | **Reviewed**    |
      | `used_for_auto_attribution`                                                                                                                                                                                                                                                                                                                                        | **Unused**        | **Consumed**    |
      | Rationale: both columns read as “pipeline stage” outcomes; **Pending/Reviewed** matches admin queue language; **Unused/Consumed** matches sync/auto-attribution without overloading “used” vs “resolved”. Optional tooltip on headers: one line explaining “Cleared from review queue after manual assign” vs “Event was applied when computing auto attribution.” |                   |                 |

    - **Single-column fallback**: If space is critical, one column **Processing** with two badges side-by-side: `[Review: Pending]` `[Auto: Unused]` using the **same** four strings above — avoid mixing synonyms (e.g. don’t pair “Unresolved” with “Not used” in the same screen).
    - **App-wide consistency**: Reuse the same i18n keys for **AdminDockerUsageReviewPage** event tables and the entity detail modal (and any future usage-event UI) so labels never drift.
3. **Wire tabs**
  - `[ContainersTab](frontend/src/components/docker/ContainersTab.tsx)`: new column after size with icon button “Details”; pass full `container_id`, `entity_type="container"`.  
  - `[ImagesTab](frontend/src/components/docker/ImagesTab.tsx)`: new column on **image** table rows (`image_id`).  
  - `[VolumesTab](frontend/src/components/docker/VolumesTab.tsx)`: new column on rows (`volume_name`, `entity_type="volume"`).
4. **i18n** `[frontend/src/i18n/index.tsx](frontend/src/i18n/index.tsx)`: strings for modal title, tab labels, empty states, errors (EN + zh-Hans).

## Scope / non-goals

- **Layers** table in `ImagesTab`: not in scope unless you explicitly want the same modal with `entity_type=image` only for parent image lookup (out of current request).  
- **Secrets**: full inspect may contain env vars; acceptable for admin-only routes consistent with `docker inspect` CLI.

## Verification

- Manual: open host device Docker UI, open modal for each entity type; confirm inspect JSON, attribution breakdown, and events load.  
- Regression: existing `/remote-api/docker/usage/events` without `include_resolved` still returns only unresolved events (review queue unchanged).

