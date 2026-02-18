# Docker Quota Implementation – Review & Decisions (resolved)

This document recorded unclear areas; decisions have been applied as below.

---

## 1. **Celery worker config** → **B: Config file**

- **Decision:** Worker loads the same config file via **CONFIG_PATH** (e.g. `CONFIG_PATH=config.slave.json celery ...`). The task `_load_slave_config()` reads `SLAVE_HOST_ID`, `MASTER_EVENT_CALLBACK_URL`, `MASTER_EVENT_CALLBACK_SECRET`, and `DOCKER_QUOTA_ENFORCEMENT_ORDER` from that JSON; env vars remain as override.

---

## 2. **Unattributed containers** → **B: Part of total, shown in UI**

- **Decision:** Unattributed usage is part of total (and thus deducted from free and percent). It is **not** part of per-user used. It is **shown in the UI** (Docker device: “Unattributed (no qman.user)” when `unattributed_usage` &gt; 0). If `DOCKER_QUOTA_RESERVED_BYTES` is not set, total = sum of attributed usage + unattributed usage.

- **Exact semantics:**  
  - **If DOCKER_QUOTA_RESERVED_BYTES is set:** total = reserved, used = attributed, free = max(0, total − attributed − unattributed). So free ∈ [0, total], hence percent = (total − free) / total is in [0, 100].  
  - **If not set:** total = **sum of user quota limits (bytes)** + unattributed (not sum of uses). used = attributed, free = max(0, total − attributed − unattributed). So free ≥ 0 and percent = (total − free) / total ≤ 100.

- **Consistency with pyquota/ZFS:** On block/ZFS, `usage.used` = total device usage and used + free = total. For Docker we define used = attributed only; free = total − attributed − unattributed (clamped ≥ 0). The difference is intentional and documented.

- **Implementation:** Backend returns `usage.used` = attributed; device has `unattributed_usage`. Frontend `DeviceUsage` accepts `otherUsageBytes` and `otherUsageLabelOverride`; for Docker we pass `otherUsageBytes={unattributed_usage}` so the bar shows free + unattributed + attributed correctly.

---

## 3. **Image usage** → **B: Later; design documented**

- **Decision:** Image usage is planned for later. Shared-image handling and further choices are documented in **`docs/DOCKER_IMAGE_QUOTA_DESIGN.md`** (count once vs per-puller vs proportional, and whether unattributed includes image layers).

---

## 4. **Setting quota to 0** → **Correct as-is**

- No change. Limit 0 is stored and excluded from enforcement.

---

## 5. **Host user not in passwd** → **A: Document; assume local passwd**

- **Decision:** Assume all users are in local passwd (no LDAP). Documented in README.

---

## 6. **No OAuth mapping → no email** → **Correct; add logging**

- **Decision:** Keep behaviour; log at **INFO** when skipping (no OAuth mapping for host_user_name). Implemented in `app/notifications.py`.

---

## 7. **NOTIFICATION_OAUTH_ACCESS_TOKEN** → **Correct; document**

- **Decision:** Document that this token is required for event-driven email (master must resolve oauth_user_id → email). Documented in README.

---

## 8. **Audit parser** → **B: Wire audit + Docker events**

- **Decision:** Wire attribution sync: parse **audit** (keys **`docker-socket`** and **`docker-client`**) and **Docker events** (container create, image pull). Track both container creation and image pulling.

- **Implementation:**  
  - `deploy/auditd-docker-quota.rules`: keys `docker-socket` and `docker-client`.  
  - `audit_parser.py`: `parse_audit_logs(keys=(...), since=...)` with default keys `docker-socket`, `docker-client`.  
  - `attribution_sync.py`: `sync_containers_from_audit()` (containers without attribution + Created time vs audit time window); `sync_from_docker_events()` (collect events since last run, correlate container create and image pull with audit, update container and image attribution).  
  - Celery task `sync_docker_attribution` and beat schedule every 120s.

---

## 9. **Enforcement order** → **Configurable; default newest first**

- **Decision:** Make enforcement policy **configurable** via **`DOCKER_QUOTA_ENFORCEMENT_ORDER`**: `newest_first` (default), `oldest_first`, or `largest_first`.

- **Implementation:** Task loads order from config (or env); `_containers_by_uid_with_created(order)` returns list of `(cid, size, created_ts)` sorted by the chosen policy.

---

## 10. **SMTP 465** → **Correct; apply fix**

- **Decision:** Use **SMTP_SSL** for port 465 (implicit TLS). Implemented in `app/notifications.py`.
