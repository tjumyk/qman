# Docker image usage and shared images – design and decisions

This note explains how image (layer) usage will be added to Docker quota using a **layer-level** approach.

---

## Current behaviour

- Only **container writable layer** size (`SizeRw`) is counted per user.
- Image layers (pull size) are **not** attributed or included in quota usage.
- `DockerImageAttribution` exists and is filled by the sync task on **image pull** (Docker event + audit correlation), but that data is not yet used when computing per-user usage or device total.

---

## Docker layer model

### How layers work

- **Images** are composed of **layers** (read-only filesystem diffs). Each layer has a unique ID (e.g. `sha256:abc123...`).
- **Layers are shared on disk**: If image A has layers `[L1, L2, L3]` and image B has layers `[L1, L2, L4]`, then layers L1 and L2 are stored **once** on disk and referenced by both images.
- **Containers** use layers from their base image(s) plus a **writable layer** (the `SizeRw` we already count).
- **Multi-image scenarios**: When a container uses image A, Docker's `inspect_image` API returns the **full layer list** including all parent layers. So if image A is based on image B, `RootFS.Layers` for image A includes all layers from B. We don't need special handling for multi-stage builds or parent images – Docker gives us the complete layer list.

### What we need

- **Layer-level attribution**: Each layer is attributed to the **first creator** (the first user who created/pulled/imported an image containing that layer).
- **Per-user image usage**: Sum of sizes of layers attributed to that user (as first creator).
- **Container layer usage**: Containers use layers from their image(s), but those layers are already attributed to the first creator (not the container owner). So container owner only gets the writable layer size.

### Ways layers can be created

Layers can be created through multiple operations:

1. **`docker pull`**: Pulls an image from a registry, creating new layers locally (if not already present).
2. **`docker build`**: Builds a new image from a Dockerfile, creating new layers during the build process.
3. **`docker commit`**: Commits a container's changes to a new image, creating a new layer from the container's writable layer.
4. **`docker import`**: Imports a tarball as a new image, creating new layers.
5. **`docker load`**: Loads an image from a tar archive, creating layers locally (if not already present).
6. **`docker tag`**: Tags an existing image (doesn't create new layers, but creates a new image reference).

**Key insight**: Only operations 1-5 can create NEW layers. Operation 6 (tag) only creates a new image reference pointing to existing layers.

---

## Decisions

### 1. Shared images: Option A – First creator owns the layer

- **Each layer is attributed to the first creator** (the first user who created/pulled/imported/loaded an image containing that layer).
- Once a layer is attributed, it stays attributed to that user even if others pull/build/commit images containing the same layer.
- **For quota enforcement**: Layers count toward the **first creator's usage**, not the container owner's usage.
  - Example: Bob pulls image A (layers L1, L2, L3) first → Bob's quota includes L1+L2+L3.
  - Alice creates a container from image A → Alice's quota includes only the container's writable layer, not L1/L2/L3 (because Bob owns them).
  - Example: Alice builds image B (creates new layer L4) → Alice's quota includes L4.
  - Example: Bob commits container C to image D (creates new layer L5) → Bob's quota includes L5.
- **Simple and deterministic**: No ambiguity about who "owns" shared layers.

### 2. Image usage counts toward quota: **Yes**

- User's quota usage = container writable layers + image layers (attributed to them as first creator).
- Enforcement compares `container_used + image_used` against `block_hard_limit`.

### 3. Unattributed includes image layers: **Yes**

- If an image (or layer) has no creator attribution (e.g. created/pulled before audit/sync, or by root), its size goes into **unattributed**.
- So `unattributed` = unattributed containers + unattributed image layers.

### 4. Image size source: **Layer-level**

- We use **layer-level sizes** (not whole-image sizes) for accurate sharing.
- Each layer has a size (from Docker API or `docker history`); we attribute layers individually.
- This correctly handles: containers using layers from multiple images, shared layers between images, and multi-stage builds.

---

## Layer-level implementation plan

### Step 1: Get layer information from Docker

**Docker API provides:**

- **Image layers**: `client.api.inspect_image(image_id)` → `RootFS.Layers` (list of layer IDs, e.g. `["sha256:abc...", "sha256:def..."]`).
- **Image total size**: `client.api.inspect_image(image_id)` → `Size` (total uncompressed size of the image).
- **Layer sizes**: Docker doesn't expose per-layer size directly via the API, but we can use:
  - **Option A**: `docker history <image>` command-line output shows incremental sizes per layer. Requires subprocess and parsing text output (less reliable, platform-dependent).
  - **Option B (recommended)**: Use Docker's image history API (`client.api.history(image_id)`) which returns structured data with layer sizes. More reliable, cleaner code, cross-platform, and uses the Docker SDK properly.
  - **Option C**: Approximate by distributing total image size proportionally across layers (less accurate but simpler).

**Implementation approach:**

1. For each image, call `client.api.inspect_image(image_id)` to get:
   - `RootFS.Layers` (list of layer IDs)
   - `Size` (total image size)
2. For each image, call `client.api.history(image_id)` to get layer sizes:
   - Returns list of dicts with `Size` field (incremental size added by each layer).
   - Note: `history` returns layers in reverse order (newest first), so we need to match with `RootFS.Layers` (oldest first).
3. Store layer-level data: `(layer_id, size_bytes, first_puller_uid)`.

### Step 2: Data model

**New table:**

```sql
docker_layer_attribution (
    layer_id VARCHAR(64) PRIMARY KEY,  -- e.g. sha256:abc123...
    first_puller_uid INTEGER,           -- uid of first user who created/pulled/imported/loaded an image with this layer
    first_puller_host_user_name VARCHAR(255),
    size_bytes INTEGER,                 -- size of this layer (incremental size from history)
    first_seen_at TIMESTAMP,            -- when we first saw this layer
    creation_method VARCHAR(32)          -- how layer was created: 'pull', 'build', 'commit', 'import', 'load' (optional, for tracking)
)
```

**Migration path:**

- Keep `DockerImageAttribution` for tracking image creation (pulls, builds, commits, imports, loads).
- Add `DockerLayerAttribution` table for layer-level attribution.
- When computing usage, use layer-level data.
- Note: Rename `first_puller_uid` to `first_creator_uid` in the implementation for clarity (or keep as-is for backward compatibility).

### Step 3: Layer attribution logic

**When an image is created/pulled/imported/loaded (any operation that can create layers):**

1. Get image's layers from `inspect_image` → `RootFS.Layers`.
2. Get layer sizes from `history` API (or parse `docker history` output).
3. For each layer:
   - Check if `layer_id` exists in `docker_layer_attribution`.
   - If not, attribute it to the current creator (from `DockerImageAttribution` or container attribution for commits).
   - If yes, keep existing attribution (first creator wins).

**Attribution sources:**

- **Pull**: Attribute to puller (from `DockerImageAttribution` via audit correlation).
- **Build**: Attribute to builder (from audit correlation with `docker build` command or Docker events).
- **Commit**: Attribute to committer (from audit correlation with `docker commit` command, or use container's attribution).
- **Import/Load**: Attribute to importer (from audit correlation with `docker import`/`load` command).
- **Tag**: No new layers created, but we may want to track the tagger for image reference attribution (optional).

**When computing per-user usage:**

1. **Container usage**: Sum of writable layer sizes of containers attributed to that user.
2. **Image usage**: Sum of `size_bytes` from `docker_layer_attribution` where `first_puller_uid = uid` (or `first_creator_uid`).
3. **Total**: `container_usage + image_usage`.

**When computing device total:**

1. Get total image size from `docker system df` (or sum of all layer sizes).
2. Get total container size from `docker system df`.
3. `total_used = container_total + image_total`.
4. `unattributed = total_used - sum(container_usage_by_uid) - sum(image_usage_by_uid)`.

### Step 4: Container layer usage

**Important**: Per your decision, layers count toward the **first puller**, not the container owner.

- When a container uses image A:
  - Container owner gets: container writable layer size only.
  - First puller of image A's layers gets: those layer sizes (already counted in their image usage).
- So containers don't add image layer usage to the container owner – layers are already attributed to the first puller.

**Examples:**

- **Pull**: Bob pulls image A (layers L1=100MB, L2=200MB, L3=50MB) → Bob's image usage = 350MB.
- **Container from pulled image**: Alice creates container C from image A (writable layer = 10MB) → Alice's container usage = 10MB. Bob's total usage = 350MB (image layers). Alice's total usage = 10MB (container writable layer only).
- **Build**: Alice builds image B (creates new layer L4=80MB) → Alice's image usage = 80MB (L4). If image B also uses layers L1, L2 from image A, those stay attributed to Bob.
- **Commit**: Bob commits container C to image D (creates new layer L5=20MB from container's writable layer) → Bob's image usage = 350MB + 20MB = 370MB (L1+L2+L3+L5).

---

## Implementation steps

### Phase 1: Add layer extraction and storage

1. **Add `DockerLayerAttribution` model** to `app/models_db.py`.
2. **Create Alembic migration** to add `docker_layer_attribution` table.
3. **Add functions to `attribution_store.py`**:
   - `get_layer_attributions()` → return all layer attributions.
   - `set_layer_attribution(layer_id, first_puller_uid, size_bytes)` → upsert layer attribution.
   - `get_layers_for_image(image_id)` → get layers for an image (from Docker API).
   - `attribute_image_layers(image_id, puller_uid)` → extract layers from image and attribute to puller.

### Phase 2: Extract layer sizes from Docker

1. **Add function to `docker_client.py`**:
   - `get_image_layers_with_sizes(image_id)` → returns `[(layer_id, size_bytes), ...]`.
   - Uses `client.api.inspect_image(image_id)` for layer IDs.
   - Uses `client.api.history(image_id)` for layer sizes (match by order, handling reverse order).

### Phase 3: Update attribution sync

1. **Modify `sync_from_docker_events()` in `attribution_sync.py`**:
   - Track image events: `pull`, `tag` (for new image references), `import`, `load`.
   - Track container events: `commit` (creates new image from container).
   - For each image event:
     - Attribute the image to the creator (via audit correlation).
     - Call `attribute_image_layers()` to extract and attribute NEW layers (layers not already in `docker_layer_attribution`).
   - For `commit` events:
     - Get the container's attribution (if available).
     - Create new image attribution for the committed image.
     - Extract layers and attribute NEW layers to the committer.
2. **Handle build events**:
   - Docker doesn't emit a direct "build" event, but when a build completes, it typically tags the image.
   - Track `tag` events and check if the image is new (not in `DockerImageAttribution`).
   - If new, attribute to builder (via audit correlation with `docker build` command).
   - Extract layers and attribute NEW layers to the builder.
3. **Add periodic sync task** (or extend existing):
   - For all images in `DockerImageAttribution`, ensure their layers are extracted and attributed.
   - For all images in Docker (via `list_images()`), check if they have attribution; if not, try to attribute via audit correlation.
   - This handles images created before layer extraction was implemented.

### Phase 4: Update usage computation

1. **Modify `_aggregate_usage_by_uid()` in `quota.py`**:
   - Add image layer usage: for each user, sum layer sizes from `docker_layer_attribution` where `first_puller_uid = uid` (or `first_creator_uid`).
   - User's total usage = container usage + image layer usage.
2. **Update device total**:
   - Include image layer sizes in `total_used` (from `docker system df` or sum of all layers).
   - Update `unattributed` to include unattributed image layers (layers not in `docker_layer_attribution`).

### Phase 5: Update enforcement

1. **Modify `enforce_docker_quota()` in `docker_quota_tasks.py`**:
   - When checking quota, use `container_used + image_used` (not just container_used).

---

## Questions answered

### Q1: "First creator owns the layer" – For quota enforcement, does this mean layers count toward first creator's usage?

**A: Yes.** Layers count toward the first creator's usage, not the container owner's usage. This means:
- Bob pulls image A first → Bob's quota includes all layers from image A.
- Alice creates containers from image A → Alice's quota includes only the container writable layers, not the image layers (because Bob owns them).
- Alice builds image B (creates new layer L4) → Alice's quota includes L4.
- Bob commits container C to image D (creates new layer L5) → Bob's quota includes L5.

### Q2: Container using layers from multiple images – How do we handle this?

**A: No special handling needed.** Docker's `inspect_image` API returns the complete layer list including all parent layers. So if image A is based on image B, `RootFS.Layers` for image A includes all layers from B. We just extract layers from the final image and attribute NEW layers (not already attributed) to the first creator.

### Q4: How do we handle build, commit, import, and load operations?

**A: Track via Docker events and audit correlation:**
- **Build**: Track `tag` events for newly built images, correlate with audit `docker build` commands, attribute new layers to builder.
- **Commit**: Track container `commit` events, correlate with audit `docker commit` commands (or use container's attribution), attribute new layer to committer.
- **Import/Load**: Track image `import`/`load` events, correlate with audit commands, attribute new layers to importer.
- **Tag**: Track `tag` events, but only attribute if the image is new (not already in `DockerImageAttribution`). Tagging doesn't create new layers, but creates new image references.

### Q3: Layer size extraction – What's the best way?

**A: Use Docker SDK's `client.api.history(image_id)` method (Option B).** It returns structured data with incremental sizes per layer. We match layers from `RootFS.Layers` (oldest first) with sizes from `history()` (newest first, so reverse order). This is better than parsing command-line output (Option A) because it's more reliable, cleaner, and cross-platform.

---

## Next steps

1. Implement `DockerLayerAttribution` model and migration.
2. Add layer extraction functions to `docker_client.py`.
3. Update attribution sync to handle all image creation methods (pull, build, commit, import, load).
4. Update usage computation to include layer usage.
5. Test with real Docker images and containers created via different methods (pull, build, commit, import, load).

## Summary: Handling all image creation methods

The design now properly handles all ways layers can be created:

- ✅ **Pull**: Track `pull` events, attribute layers to puller.
- ✅ **Build**: Track `tag` events for new images, correlate with `docker build` audit commands, attribute new layers to builder.
- ✅ **Commit**: Track container `commit` events, correlate with `docker commit` audit commands (or use container attribution), attribute new layer to committer.
- ✅ **Import/Load**: Track `import`/`load` events, correlate with audit commands, attribute new layers to importer.
- ✅ **Tag**: Track `tag` events, but only create image attribution if image is new. No new layers created.

All new layers are attributed to the first creator, ensuring accurate quota tracking regardless of how the layer was created.
