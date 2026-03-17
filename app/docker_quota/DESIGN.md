# Docker Quota: Audit Parsing and Attribution Design

This document describes the design and key decisions for attributing Docker container and image usage to users using Linux audit logs and Docker events.

## Overview

- **Goal:** Associate each container (and image usage) with a Unix user (uid) for quota and accountability.
- **Data sources:**
  1. **Audit logs** (auditd): who ran which `docker` command and when (via `docker-client` and `docker-socket` keys).
  2. **Docker API:** container/image events (create, destroy, pull, load, etc.) and container list with creation timestamps.
- **Flow:** Parse audit logs → extract docker subcommand and timestamp → match to Docker events by time and action type → store attribution (container_id → uid/host_user_name).

## Command Parsing

### Subcommand extraction

The audit log records process titles (e.g. `docker run -it --rm redis:alpine`). We need the **verb** (subcommand) to decide whether an audit event can explain a given Docker event (e.g. only `run`/`create` for container create).

- **Legacy form:** `docker run ...`, `docker pull ...`, `docker build ...` → verb is the first token.
- **Object form:** Docker CLI also supports management commands: `docker container run ...`, `docker image pull ...`, `docker buildx build ...`, `docker builder build ...`. Here the first token is the **object** and the second is the **verb**.

`extract_docker_subcommand(proctitle)` in `audit_parser.py` normalizes both forms so that:

| Proctitle (simplified)           | Extracted subcommand |
|---------------------------------|----------------------|
| `docker run ...`                | `run`                |
| `docker container run ...`      | `run`                |
| `docker pull ...`               | `pull`               |
| `docker image pull ...`         | `pull`               |
| `docker build ...`              | `build`              |
| `docker buildx build ...`       | `build`              |
| `docker builder build ...`      | `build`              |
| `docker start 2027`            | `start`              |
| `docker volume create myvol`   | `volume` (see below) |

Rules:

1. Input must start with `docker ` (not `docker-compose`).
2. First token after `docker` must start with a letter `[a-z]`, so container ID prefixes (e.g. `2027`, `33f7fa7dcbfb`) are never treated as the subcommand.
3. **Object form:** If the first token is one of `container`, `image`, `buildx`, `builder`, we take the **next** token as the verb. All other first tokens are treated as the subcommand (legacy or object name).

### Why only four object types?

Docker’s CLI has many management commands: `builder`, `buildx`, `checkpoint`, `compose`, `config`, `container`, `context`, `image`, `manifest`, `network`, `node`, `plugin`, `secret`, `service`, `stack`, `swarm`, `system`, `trust`, `volume`. We could treat all of them as “object + verb” and always take the second token. We intentionally **do not** do that for attribution safety:

- If we treated `volume` as an object, `docker volume create myvol` would yield verb **`create`**.
- We match audit events to **container** create events by requiring subcommand in `{run, create}`.
- An audit event with subcommand `create` from `docker volume create` could then be matched to a **container** create and wrongly attribute that container to the user who only created a volume.

So we only use object form for objects whose verb can legitimately be one of the attribution-relevant verbs we care about:

- **container** → `run`, `create` (container create)
- **image** → `pull`, `build`, … (image operations)
- **buildx** → `build`
- **builder** → `build`, `prune`

All other management commands (e.g. `volume`, `network`, `config`, `compose`) are left as “first token = subcommand”. So `docker volume create` yields `volume` (categorized as “other”), not `create`, and cannot match container-create attribution.

### Subcommand categories

`DOCKER_SUBCOMMAND_CATEGORIES` in `audit_parser.py` groups verbs for filtering and diagnostics:

- **container_create:** `run`, `create` — used to attribute container create events.
- **image_create:** `pull`, `build`, `load`, `import`, `commit` — used for image attribution.
- **container_exec:** `exec` — for future use.
- **other:** everything else (e.g. `ps`, `ls`, `start`, `stop`, `volume`, `context`, `builder`, …).

The reverse map `SUBCOMMAND_TO_CATEGORY` is used by `get_subcommand_category()`.

## Attribution Logic

### Action → subcommand mapping

In `attribution_sync.py`, `ACTION_TO_SUBCOMMANDS` maps each Docker event action to the set of docker subcommands that can cause it:

| Docker event action | Required audit subcommand(s)     |
|---------------------|----------------------------------|
| create (container)  | `run`, `create`                  |
| pull                | `pull`                           |
| load                | `load`                           |
| import              | `import`                         |
| tag                 | `build`, `tag`                   |
| commit              | `commit`                         |

When matching an audit event to a Docker event, we only consider audit events whose extracted subcommand is in this set for the given action.

### Container attribution from audit only

`sync_containers_from_audit()`:

1. Lists containers without attribution (and without `qman.user` label).
2. Runs `ausearch` for keys `docker-socket`, `docker-client` with a time range (`AUDIT_LOOKBACK`, e.g. 90m).
3. Parses output, extracts `docker_subcommand` per event, and keeps only events with subcommand in `ACTION_TO_SUBCOMMANDS["create"]` (i.e. `run` or `create`). This avoids attributing containers to users who only ran `docker ps` or `docker container ls`.
4. For each container, finds the audit event whose timestamp is closest to the container’s `Created` time within a symmetric **time window** (`TIME_WINDOW_SECONDS` = 120s).
5. Attributes the container to that audit event’s uid (prefer `auid`, then `uid`, then `euid`).

Containers with label `qman.user` are attributed directly from the label and are not matched from audit.

### Container and image attribution from Docker events

`sync_from_docker_events()`:

1. Fetches Docker events since last run (e.g. container create, image pull, load, tag, commit).
2. Builds an audit event list (with `docker_subcommand`) for the same lookback.
3. For each **container create** event: finds the best matching audit event with subcommand in `{run, create}` within a **symmetric** time window (container create is quick).
4. For **image** events (pull, load, import, tag, commit): uses an **asymmetric** time window: long lookback (`LONG_COMMAND_LOOKBACK_SECONDS` = 600s), small forward buffer (`LONG_COMMAND_FORWARD_SECONDS` = 10s), because the audit event marks command **start** and the Docker event marks **completion**.

So:

- **Quick commands** (container create, commit): symmetric ±120s.
- **Long-running commands** (pull, build, load, import): audit can be up to 10 minutes before the Docker event; small forward window for clock skew.

### Time windows (summary)

| Constant                     | Value  | Use |
|-----------------------------|--------|-----|
| `TIME_WINDOW_SECONDS`       | 120    | Symmetric window for container create and quick operations. |
| `LONG_COMMAND_LOOKBACK_SECONDS` | 600 | Lookback for long-running commands (pull, build, load, import). |
| `LONG_COMMAND_FORWARD_SECONDS`  | 10  | Forward buffer for clock skew in long-command matching. |
| `AUDIT_LOOKBACK`            | 90m    | How far back to query audit logs (ausearch -ts). |

## Design Decisions Summary

1. **Only `container`, `image`, `buildx`, `builder` use object form** so that `docker volume create` / `docker network create` never produce verb `create` and cannot be mistaken for container create.
2. **Container create attribution uses only `run` and `create`** so that listing/inspection commands (`docker ps`, `docker container ls`, etc.) do not attribute containers.
3. **First token must start with a letter** so numeric or hex container ID prefixes in the proctitle are never interpreted as the subcommand (e.g. `docker start 2027` → `start`).
4. **Asymmetric window for long-running commands** so that pull/build/load/import completion events are matched to the correct audit event (command start) even when the operation takes several minutes.
5. **Audit keys** `docker-socket` and `docker-client` are used by default; both are needed to see who invoked the client and who triggered socket access.
6. **Prefer `auid`** when available for attribution, as it reflects who initiated the session/action.

## References

- Docker CLI reference: [docs.docker.com/reference/cli/docker](https://docs.docker.com/reference/cli/docker)
- Management commands (object + verb): e.g. `docker container`, `docker image`, `docker buildx`, `docker builder`, `docker volume`, etc.
- Implementation: `app/docker_quota/audit_parser.py` (parsing, categories), `app/docker_quota/attribution_sync.py` (matching, time windows, storage).
