# How container attribution is collected from auditd and Docker events

This document explains how we attribute Docker containers **that do not have the `qman.user` label** to a Unix user (uid) using auditd logs and Docker API events. The result is stored in the `docker_container_attribution` table and used for quota reporting and enforcement.

---

## 1. Overview

We have two ways to learn “who created this container” when there is no label:

1. **Audit-only path:** List all containers, take each container’s **Created** timestamp, and find an **audit event** (Docker socket or binary access) from the same user in a short time window around that timestamp. We assume that user created the container.
2. **Docker-events path:** Consume **Docker API events** (e.g. `container create`, `image pull`), get the event’s timestamp and resource id, and again find an **audit event** in a short time window with the same timestamp. We attribute the container/image to that user.

Both paths rely on **time-window correlation**: we never see the container id in the audit log; we only see “uid X touched Docker at time T”. So we match “container created at time T” (from Docker) with “uid X touched Docker at time T′” (from audit) when T and T′ are close (e.g. within 120 seconds), and assign that uid to the container.

---

## 2. What auditd records

### 2.1 Rules (deploy/auditd-docker-quota.rules)

We install two rules with **different keys** so we can tell socket access from client execution:

- **`docker-socket`:** Any read/write/execute/append on `/var/run/docker.sock`.  
  So any process talking to the Docker daemon (create container, pull image, etc.) triggers this.
- **`docker-client`:** Execution of `/usr/bin/docker`.  
  So when a user runs the `docker` CLI we get an event.

Both are needed because:

- A process can talk to the socket without running `/usr/bin/docker` (e.g. Python `docker` SDK, or another client).
- Running `docker` will both execute the binary and access the socket, so we get two events; that’s fine.

Rule syntax:

```text
-w /var/run/docker.sock -p rwxa -k docker-socket
-w /usr/bin/docker -p x -k docker-client
```

After adding rules, auditd must be restarted (e.g. `systemctl restart auditd` or `service auditd restart`).

### 2.2 What we get from the audit log

We query with **ausearch** for keys `docker-socket` and `docker-client`:

```bash
ausearch -i -k docker-socket -k docker-client -ts recent -ts 60m
```

Each audit record is a multi-line block. We care about:

- **uid** – user id of the process that accessed the socket or ran the binary.
- **time** – when the event happened (format depends on ausearch; we support Unix timestamp or `MM/DD/YYYY HH:MM:SS`).
- **msg**, **type**, **key**, **pid** – we parse them but correlation uses mainly uid + time.

We do **not** get the container id or image id from the audit log. So we cannot directly say “this audit line is for container X”. We only get “uid U did something with Docker at time T”. That is why we need time-window matching with Docker’s creation/pull time.

---

## 3. How we parse the audit log (audit_parser.py)

- **Entry point:** `parse_audit_logs(keys=("docker-socket", "docker-client"), since="60m")`.
- **Command:** `ausearch -i -k docker-socket -k docker-client -ts recent -ts 60m` (and optionally `--input <file>`).
- **Parsing:** We walk the output line by line. A line starting with `----` starts a new event. Lines like `key=value` set fields on the current event. We keep **uid**, **pid**, **msg**, **type**, **key**, and **time** (stored as `timestamp`).
- **Timestamp handling:** We support:
  - Numeric string (Unix seconds, possibly with decimals).
  - Date string `MM/DD/YYYY HH:MM:SS` (parsed to Unix timestamp).
- **Result:** List of `{uid, pid, timestamp, msg, type, key}`. We then build a list of `(timestamp, uid)` sorted by time for correlation.

If `ausearch` is not installed or fails, we return an empty list and attribution from audit is effectively disabled.

---

## 4. What Docker events give us (docker_client.py)

The Docker daemon emits a stream of **events** (container create/start/die, image pull, etc.). We use the **Events API** with a `since` time so we only get events after the last run.

- **API:** `client.events(since=since_dt, decode=True)`. This is a blocking stream.
- **Collection:** `collect_events_since(since_ts, max_seconds=5.0, max_events=500)` runs the stream in a thread and stops after `max_seconds` or when it has collected `max_events` events, so the sync task doesn’t block forever.
- **Fields we keep:** For each event we store **type** (e.g. `container`, `image`), **action** (e.g. `create`, `pull`), **id** (container id or image id), **time_nano** (event time in nanoseconds; we convert to seconds for comparison).

So for a container created without `qman.user` we get an event like:

- `type=container`, `action=create`, `id=<full container id>`, `time_nano=<ns>`.

We do **not** get uid from Docker events; the daemon doesn’t know which user triggered the action. So we again rely on matching this event’s time to an audit event’s time and use the audit event’s uid.

---

## 5. The two sync paths (attribution_sync.py)

A **Celery beat task** runs **`sync_docker_attribution`** every 120 seconds. It calls:

1. `sync_containers_from_audit()` – audit + container list.
2. `sync_from_docker_events()` – audit + Docker events.

Then it persists the “last event timestamp” for the next run.

### 5.1 Path 1: sync_containers_from_audit()

**Idea:** For every container that (a) has no row in `docker_container_attribution` and (b) has no `qman.user` label, we get its **Created** time from the Docker API and try to find an audit event in a time window around that time.

**Steps:**

1. Load current attributions and list all containers from the Docker API (`list_containers(all=True)`).
2. Parse audit for the last 60 minutes: `parse_audit_logs(keys=("docker-socket","docker-client"), since="60m")`.
3. Build a list of `(timestamp, uid)` from audit events (parsing `time` as above), sort by timestamp.
4. For each container:
   - Skip if it already has an attribution or has `qman.user`.
   - Get `Created` (ISO string), convert to Unix timestamp with `_parse_created_iso()`.
   - Search the audit list for the **closest** `(timestamp, uid)` such that `|timestamp - created_ts| <= TIME_WINDOW_SECONDS` (120 seconds). If found, assign that **uid** to the container.
5. Resolve uid to username with `pwd.getpwuid(uid).pw_name` and call `set_container_attribution(container_id, host_user_name, uid, image_id, 0)`.

So we’re saying: “This container was created at T; the only Docker-related audit we have near T is uid U, so we attribute the container to U.”

**Limitation:** Containers created a long time ago may have no audit events left in the last 60 minutes, so they stay unattributed unless path 2 saw them when they were created.

### 5.2 Path 2: sync_from_docker_events()

**Idea:** We remember the last time we ran (`docker_events_last_ts` in the settings table). We ask Docker for all events **since** that time, then for each `container create` (and `image pull`) we again find an audit event in a 120-second window and assign the uid.

**Steps:**

1. Read `docker_events_last_ts` from the settings table (or default to 24 hours ago).
2. Call `collect_events_since(since_ts, max_seconds=5, max_events=500)` to get recent Docker events (container create, image pull, etc.).
3. Parse audit again for the last 60 minutes and build the same `(timestamp, uid)` list.
4. For each Docker event:
   - **Container create:** If `type=container` and `action=create`, and this container id is not yet attributed, convert the event’s `time_nano` to seconds (`ev_ts`). Find the audit event with the closest timestamp in the 120-second window. If found, call `set_container_attribution(container_id, name, uid, ...)`.
   - **Image pull:** If `type=image` and `action=pull`, same idea: match by time to an audit event and call `set_image_attribution(image_id, name, uid, 0)`.
5. Write the current time back to `docker_events_last_ts` so the next run only asks for events after this run.

So we’re saying: “Docker says container C was created at T; the only Docker-related audit near T is uid U, so we attribute C to U.”

**Why both paths:** Path 1 catches containers that already existed before we had events (e.g. we only keep 60 minutes of audit, but the container’s **Created** time is still in the past). Path 2 catches creates (and pulls) that happen after the previous sync, with exact event timestamps. Running both every 120 seconds keeps attributions up to date.

---

## 6. Time window and “closest” match

- **TIME_WINDOW_SECONDS = 120:** We only consider an audit event and a Docker create/pull time as related if they are at most 120 seconds apart. This avoids matching unrelated activity (e.g. user A created a container at 10:00, user B ran `docker ps` at 10:02).
- **Closest match:** Among all audit events in the window, we pick the one with the **smallest** `|audit_time - docker_time|` and use that uid. So we prefer the audit line that is temporally closest to the create/pull.

If no audit event falls in the window, we do not attribute that container/image (it stays “unattributed” for quota and is not charged to any user until a later run finds a match or an admin adds a label).

---

## 7. Persistence and scheduling

- **Attribution store:** All attributions are stored in the DB: `docker_container_attribution` (container_id, host_user_name, uid, image_id, size_bytes), and optionally `docker_image_attribution` for image puller.
- **Last events timestamp:** `sync_from_docker_events()` reads and writes the key `docker_events_last_ts` in the `settings` table so we never re-process the same events and we don’t miss events between runs (we use `since=<last_ts>`).
- **When it runs:** The Celery beat schedule runs `sync_docker_attribution` every 120 seconds (see `app/celery_app.py`). The worker must have access to the same DB (for settings and attribution tables) and to the Docker socket (for `list_containers` and `client.events()`), and the host must have auditd and `ausearch` if you want audit-based attribution.

---

## 8. Summary flow (containers without qman.user)

1. **Audit:** Rules `docker-socket` and `docker-client` record who (uid) touched the socket or ran the binary and when (time).
2. **Audit parsing:** We run `ausearch -k docker-socket -k docker-client -ts recent -ts 60m`, parse uid and time, and build a sorted list of (timestamp, uid).
3. **Container list path:** For each container without attribution and without label, we take Docker’s **Created** time and find the closest audit (uid) within 120 seconds; we store that uid as the container’s owner.
4. **Docker events path:** We ask Docker for events since last run; for each `container create` (and `image pull`) we take the event time and again find the closest audit uid in a 120-second window and store the attribution.
5. **Result:** Containers get an owner (uid/username) in `docker_container_attribution`, which quota and enforcement use. If no audit event is in the window, the container stays unattributed until a future run or until someone sets `qman.user` (e.g. by recreating the container with the label).
