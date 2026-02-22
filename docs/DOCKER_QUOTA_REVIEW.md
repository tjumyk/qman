# Docker Quota Implementation - Review & Decisions (resolved)

This document recorded unclear areas; decisions have been applied as below.

---

## 1. **Celery worker config** - **B: Config file**

- **Decision:** Worker loads the same config file via **CONFIG_PATH** (e.g. `CONFIG_PATH=config.slave.json celery ...`). The task `_load_slave_config()` reads `SLAVE_HOST_ID`, `MASTER_EVENT_CALLBACK_URL`, `MASTER_EVENT_CALLBACK_SECRET`, and `DOCKER_QUOTA_ENFORCEMENT_ORDER` from that JSON; env vars remain as override.

---

## 2. **Unattributed containers** - **B: Part of total and used, shown in UI**

- **Decision:** Unattributed usage is part of both total and used (consistent with pyquota/ZFS semantics where `used + free = total`).

- **Exact semantics:**
  - **If DOCKER_QUOTA_RESERVED_BYTES is set:** total = reserved, used = attributed + unattributed, free = max(0, total - used). So free is in [0, total], hence percent = used / total is in [0, 100].
  - **If not set:** total = **sum of user quota limits (bytes)** + unattributed. used = attributed + unattributed, free = max(0, total - used). So free >= 0 and percent <= 100.

- **Consistency with pyquota/ZFS:** Now consistent: `usage.used` = total consumed space (attributed + unattributed), and `used + free = total`.

- **Implementation:** Backend returns `usage.used` = attributed + unattributed; device has `unattributed_usage` for detailed breakdown. Frontend `DeviceUsage` computes `otherUsage = used - trackedUsage` (same formula for all device types), so the bar shows tracked + other + free correctly.

---

## 3. **Image usage** - **Implemented: Layer-level attribution**

- **Decision:** Image usage is now implemented with layer-level attribution. Shared-image handling and further details are documented in **`docs/DOCKER_IMAGE_QUOTA_DESIGN.md`** (first creator owns layer, unattributed includes image layers without attribution).

---

## 4. **Setting quota to 0** - **Correct as-is**

- No change. Limit 0 is stored and excluded from enforcement.

---

## 5. **Host user not in passwd** - **A: Document; assume local passwd**

- **Decision:** Assume all users are in local passwd (no LDAP). Documented in README.

---

## 6. **No OAuth mapping -> no email** - **Correct; add logging**

- **Decision:** Keep behaviour; log at **INFO** when skipping (no OAuth mapping for host_user_name). Implemented in `app/notifications.py`.

---

## 7. **NOTIFICATION_OAUTH_ACCESS_TOKEN** - **Correct; document**

- **Decision:** Document that this token is required for event-driven email (master must resolve oauth_user_id -> email). Documented in README.

---

## 8. **Audit parser** - **B: Wire audit + Docker events**

- **Decision:** Wire attribution sync: parse **audit** (keys **`docker-socket`** and **`docker-client`**) and **Docker events** (container create, image pull). Track both container creation and image pulling.

- **Implementation:**
  - `deploy/auditd-docker-quota.rules`: keys `docker-socket` and `docker-client`.
  - `audit_parser.py`: `parse_audit_logs(keys=(...), since=...)` with default keys `docker-socket`, `docker-client`.
  - `attribution_sync.py`: `sync_containers_from_audit()` (containers without attribution + Created time vs audit time window); `sync_from_docker_events()` (collect events since last run, correlate container create and image pull with audit, update container and image attribution).
  - Celery task `sync_docker_attribution` and beat schedule every 120s.

---

## 9. **Enforcement order** - **Configurable; default newest first**

- **Decision:** Make enforcement policy **configurable** via **`DOCKER_QUOTA_ENFORCEMENT_ORDER`**: `newest_first` (default), `oldest_first`, or `largest_first`.

- **Implementation:** Task loads order from config (or env); `_containers_by_uid_with_created(order)` returns list of `(cid, size, created_ts)` sorted by the chosen policy.

---

## 10. **SMTP 465** - **Correct; apply fix**

- **Decision:** Use **SMTP_SSL** for port 465 (implicit TLS). Implemented in `app/notifications.py`.
