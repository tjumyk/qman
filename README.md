# Quota Manager (qman)

Quota management UI: master aggregates quotas from slave hosts; slaves expose local quota data via a remote API.

## Quick Start

```bash
# 1. Setup
conda create -n qman python=3.11
conda activate qman
pip install -r requirements.txt
git submodule update --init  # Initialize OAuth submodule
alembic upgrade head

# 2. Configure
cp config.master_example.json config.json
cp config.slave_mock_example1.json config.slave.json

# 3. Configure OAuth (for local dev)
# Edit oauth.config.json and set:
#   "enabled": true,
#   "server": {"url": "http://localhost:8077"},
#   "client": {"url": "http://localhost:5173"}

# 4. Run (all services)
./scripts/dev.sh

# 5. Open http://localhost:5173 and log in as "alice" or "charlie"
```

See [Run](#run) section below for detailed instructions and production deployment.

## Backend (Python 3.11+)

- **Stack:** Flask 3+, Pydantic 2+, SQLAlchemy 2, Alembic, gunicorn
- **Config:** Use `config.json` for the master server and `config.slave.json` for the slave server. Copy from example configs and adjust.
- **Auth:** OAuth via the `auth_connect` submodule (`git submodule update --init`). The submodule includes a minimal mock OAuth server for local development.

### Setup

**1. Create conda environment:**

```bash
conda create -n qman python=3.11
conda activate qman
```

**2. Install dependencies:**

```bash
pip install -r requirements.txt
```

**3. Initialize OAuth submodule:**

```bash
git submodule update --init
```

**4. Configure:**

```bash
# Master server config
cp config.master_example.json config.json

# Slave server config (choose one):
cp config.slave_example.json config.slave.json        # Real quota backends
# OR for mock/testing:
cp config.slave_mock_example1.json config.slave.json  # Mock host1
```

**5. Setup database:**

```bash
# Run migrations (creates SQLite DB for dev, or uses DATABASE_URL if set)
alembic upgrade head
```

**Database options:**
- **Development:** SQLite (`sqlite:///qman.sqlite` by default, or set `DATABASE_URL`)
- **Production:** PostgreSQL (set `DATABASE_URL` to your PostgreSQL connection string)

### Mock OAuth Server (Development)

The mock OAuth server lives in the `auth_connect` submodule and loads mock users from `oauth.mock.config.json`. Use it when `oauth.config.json` points at `server.url: "http://localhost:8077"`.

**Configure OAuth:** In `oauth.config.json` set:
```json
{
  "enabled": true,
  "server": {"url": "http://localhost:8077"},
  "client": {"url": "http://localhost:5173"}
}
```

**Run mock OAuth server:**
```bash
python auth_connect/mock_oauth_server.py
# Serves on http://localhost:8077
```

**Mock users** (from `oauth.mock.config.json`):
- **alice** – Regular user (sees "My usage" only)
- **charlie** – Admin (sees "Manage" and can set quotas)

Optional env vars: `MOCK_OAUTH_PORT`, `MOCK_OAUTH_CLIENT_ID`, `MOCK_OAUTH_CLIENT_SECRET`, `MOCK_OAUTH_REDIRECT_URL`. Connect URL supports `?user_id=1` or `?user_id=2` to log in as specific users.

### Run

**Overview:** The qman system consists of:
- **Master server** – Aggregates quotas from slaves, provides UI API, sends email notifications
- **Slave server(s)** – Expose local quota data (pyquota/ZFS/Docker)
- **Docker quota worker** (optional) – Celery worker for quota enforcement (only if `USE_DOCKER_QUOTA` is enabled)
- **Docker quota beat** (optional) – Celery beat scheduler for periodic tasks (only if `USE_DOCKER_QUOTA` is enabled)
- **Frontend** – React SPA (dev server or built static files)

#### Development Mode

**Option 1: Quick start (all-in-one script):**

```bash
# From project root - starts mock OAuth, slave, master, and frontend
./scripts/dev.sh
# Then open http://localhost:5173
```

**Option 2: Manual start (separate terminals):**

**1. Master server** (uses `config.json`, default port 8436):

```bash
python run.py
# Serves on http://localhost:8436
```

**2. Slave server** (uses `config.slave.json`):

```bash
CONFIG_PATH=config.slave.json python run.py
# Port from config (default 8436, or set PORT in config)
```

**3. Docker quota worker** (only if `USE_DOCKER_QUOTA` is enabled):

**Prerequisites:** Redis must be running (used as Celery broker/backend).

```bash
# Terminal 3a: Worker (processes enforcement tasks)
CONFIG_PATH=config.slave.json celery -A app.celery_app:celery_app worker -Q qman.docker

# Terminal 3b: Beat scheduler (runs periodic tasks: enforcement every 5min, sync every 2min)
CONFIG_PATH=config.slave.json celery -A app.celery_app:celery_app beat
```

**Note:** In mock mode (`MOCK_QUOTA: true`), Celery is not required (no enforcement runs, but quota display works).

**4. Frontend dev server:**

```bash
cd frontend && npm run dev
# Serves on http://localhost:5173
```

#### Production Mode

**Master server:**

```bash
gunicorn -w 4 -b 0.0.0.0:8436 "run:app"
# Or with custom config: CONFIG_PATH=config.prod.json gunicorn -w 4 -b 0.0.0.0:8436 "run:app"
```

**Slave server:**

```bash
CONFIG_PATH=config.slave.json gunicorn -w 4 -b 0.0.0.0:8436 "run:app"
```

**Docker quota worker (production):**

**Prerequisites:** Redis must be running and accessible at `CELERY_BROKER_URL`.

```bash
# Worker (run multiple instances for high availability)
CONFIG_PATH=config.slave.json celery -A app.celery_app:celery_app worker -Q qman.docker --concurrency=4

# Beat scheduler (run single instance - only one beat process per slave)
CONFIG_PATH=config.slave.json celery -A app.celery_app:celery_app beat
```

**Production deployment notes:**
- Use a process manager (systemd, supervisor, etc.) to manage all processes (master, slave, workers, beat)
- Ensure Redis is running and accessible for Celery broker/backend
- Run beat scheduler as a single instance (multiple instances will cause duplicate tasks)
- Run multiple worker instances for high availability and load distribution
- Set appropriate `--concurrency` based on your workload

#### Mock Mode (Development/Testing)

**Slave in mock mode** uses in-memory mock data (no pyquota/Docker/ZFS required). Set `"MOCK_QUOTA": true` in `config.slave.json`, then run the slave normally. Optional **MOCK_HOST_ID** selects which mock host to use; default is `host1`.

**Available mock hosts:**

- **config.slave_mock_example1.json** → `MOCK_HOST_ID: "host1"` (Port 8437)
  - Many block devices (`/dev/sda1`, `/dev/sdb1`, `/dev/nvme0n1p1`, etc.)
  - Users: alice, bob, charlie, diana, eve
  - Mixed quota scenarios (over quota, under quota, etc.)

- **config.slave_mock_example2.json** → `MOCK_HOST_ID: "host2"` (Port 8438)
  - One ext4 device (`/dev/vdb1`) + one ZFS dataset (`tank/home`)
  - Users: alice, bob
  - Use to test mixed ext4 + ZFS UI (inode fields hidden for ZFS)

- **config.slave_mock_example3.json** → `MOCK_HOST_ID: "host3"` (Port 8439)
  - ZFS-only (no block devices)
  - Datasets: `tank/home`, `tank/scratch`
  - Users: alice, bob
  - Config: `USE_PYQUOTA: false`, `USE_ZFS: true`

- **config.slave_mock_example4.json** → `MOCK_HOST_ID: "host4"` (Port 8440)
  - One ext4 device (`/dev/sda1`) + Docker quota enabled
  - Users: alice (10 GiB quota), bob (15 GiB), charlie (5 GiB, over quota)
  - Includes unattributed usage (2 GiB)
  - Config: `USE_PYQUOTA: true`, `USE_DOCKER_QUOTA: true`
  - **Note:** Docker quota mock doesn't require Celery/Redis (no enforcement, but quota display works)

**To use a mock host:**

```bash
# Copy example config
cp config.slave_mock_example1.json config.slave.json

# Or edit config.slave.json and set:
#   "MOCK_QUOTA": true,
#   "MOCK_HOST_ID": "host1"  # or host2, host3, host4

# Run slave
CONFIG_PATH=config.slave.json python run.py
```

### Slave Quota Backends

The slave can use one or more quota backends simultaneously. When `MOCK_QUOTA` is `false`, **at least one backend must be enabled**.

#### Available Backends

**1. USE_PYQUOTA** (default: `true`)
- **Purpose:** Report and set user/group quotas on block devices (ext4/XFS) via quotactl
- **Requirements:** Filesystem must be mounted with `usrquota` and/or `grpquota` options
- **Devices:** Block devices (e.g. `/dev/sda1`, `/dev/nvme0n1p1`)
- **Quota types:** Both block (space) and inode quotas supported
- **Use case:** Traditional ext4/XFS filesystems with kernel quota support
- **Config:** Set `USE_PYQUOTA: true` in `config.slave.json`
- **Note:** Set to `false` on ZFS-only or Docker-only hosts to avoid importing pyquota

**2. USE_ZFS** (default: `false`)
- **Purpose:** Report and set ZFS user quotas per dataset
- **Requirements:** ZFS filesystem with user quotas enabled
- **Devices:** ZFS datasets (e.g. `tank/home`, `tank/scratch`)
- **Quota types:** Space-only (no inode limits in the UI)
- **Use case:** ZFS-based storage systems
- **Config:** 
  ```json
  {
    "USE_ZFS": true,
    "ZFS_DATASETS": ["tank/home", "tank/scratch"]  // Optional: omit to auto-discover all mounted ZFS filesystems
  }
  ```
- **API:** When setting quota, use dataset name as `device` parameter (e.g. `device=tank/home`)

**3. USE_DOCKER_QUOTA** (default: `false`)
- **Purpose:** Virtual Docker device quota (container writable layers + image layers)
- **Requirements:** Docker daemon, Redis (for Celery), auditd (optional, for attribution)
- **Devices:** Virtual device named `docker` (mount point: `/var/lib/docker` or `DOCKER_DATA_ROOT`)
- **Quota types:** Space-only (no inode limits)
- **Use case:** Docker container and image storage quota management
- **Config:** See [Docker quota (slave)](#docker-quota-slave) section below for full configuration
- **API:** When setting quota, use `device=docker`
- **Note:** Requires Celery worker and beat scheduler for enforcement (see [Run](#run) section)

#### Backend Combinations

You can enable multiple backends simultaneously. The slave will merge all devices into a single device list:

- **ext4 + ZFS:** `USE_PYQUOTA: true, USE_ZFS: true` – Shows both block devices and ZFS datasets
- **ext4 + Docker:** `USE_PYQUOTA: true, USE_DOCKER_QUOTA: true` – Shows block devices and Docker device
- **ZFS + Docker:** `USE_ZFS: true, USE_DOCKER_QUOTA: true` – Shows ZFS datasets and Docker device
- **All three:** `USE_PYQUOTA: true, USE_ZFS: true, USE_DOCKER_QUOTA: true` – Shows all device types

**Example config (ext4 + ZFS + Docker):**
```json
{
  "USE_PYQUOTA": true,
  "USE_ZFS": true,
  "ZFS_DATASETS": ["tank/home"],
  "USE_DOCKER_QUOTA": true,
  "CELERY_BROKER_URL": "redis://localhost:6379/0"
}
```

#### Device Identification

When setting quotas via API (`PUT /remote-api/quotas/users/<uid>?device=...`), the `device` parameter depends on the backend:

- **pyquota:** Block device path (e.g. `device=/dev/sda1`)
- **ZFS:** Dataset name (e.g. `device=tank/home`)
- **Docker:** Virtual device name (e.g. `device=docker`)

The slave automatically routes to the correct backend based on the device identifier.

### Docker quota (slave)

When **USE_DOCKER_QUOTA** is `true`, the slave exposes a virtual “Docker” device (same device-list shape as block/ZFS). Attribution of containers to users is by label **`qman.user=username`** at create time and/or by **auditd + Docker events** (periodic sync task). Set quota via the same API with `device=docker`. Enforcement runs in a Celery worker: over-quota users have containers stopped and removed; order is configurable (**`DOCKER_QUOTA_ENFORCEMENT_ORDER`**: `newest_first` (default), `oldest_first`, or `largest_first`). Unattributed usage (containers without attribution) is part of device total and free, and is shown in the UI as “Unattributed (no qman.user)”. Events (quota exceeded, container removed) can be sent to the master for email notifications.

- **Config (slave):** `USE_DOCKER_QUOTA`, `DOCKER_DATA_ROOT` (optional), `DOCKER_QUOTA_RESERVED_BYTES` (optional), `CELERY_BROKER_URL`, `DOCKER_QUOTA_ENFORCE_INTERVAL_SECONDS` (default 300), `DOCKER_QUOTA_ENFORCEMENT_ORDER` (default `newest_first`), `SLAVE_HOST_ID`, `MASTER_EVENT_CALLBACK_URL`, `MASTER_EVENT_CALLBACK_SECRET`. See `config.slave_docker_example.json`.
- **Config (master):** `SMTP_*`, `NOTIFICATION_FROM`, **`NOTIFICATION_OAUTH_ACCESS_TOKEN`** (required for event-driven email: token must have permission to call OAuth “user by id” API), `SLAVE_EVENT_SECRET`. See `config.master_example.json`.
- **Assumptions:** All host users are in local passwd (no LDAP); use `qman.user` label when creating containers if you want immediate attribution, or rely on audit + sync.
- **Auditd:** Copy `deploy/auditd-docker-quota.rules` to `/etc/audit/rules.d/` and restart auditd. Rules use keys **`docker-socket`** and **`docker-client`** so the sync task can correlate container create and image pull with uid.
- **Run worker and beat:** Both load **CONFIG_PATH** so the same config file drives Flask and Celery:
  ```bash
  # Worker (processes enforcement tasks)
  CONFIG_PATH=config.slave.json celery -A app.celery_app:celery_app worker -Q qman.docker
  
  # Beat scheduler (runs periodic tasks: enforcement every 5min, sync every 2min)
  CONFIG_PATH=config.slave.json celery -A app.celery_app:celery_app beat
  ```
  **Note:** In mock mode (`MOCK_QUOTA: true`), Celery is not required (no enforcement runs, but quota display works).
- **Image usage:** Both container writable layers and image layers count toward quota. Image layers are attributed to the first creator (first puller/builder/committer/importer/loader). See `docs/DOCKER_IMAGE_QUOTA_DESIGN.md` for details on layer-level attribution and shared-image handling.

### Quota block units (pyquota)

The backend uses [pyquota](https://github.com/tjumyk/pyquota) (quotactl wrapper). Its API uses **different units** for block usage vs limits:

- **`block_hard_limit`**, **`block_soft_limit`**: in **1K blocks** (1024 bytes per unit).
- **`block_current`**: in **bytes**.

The API and frontend follow this convention: limits are exposed in 1K blocks, current usage in bytes. The UI converts limits to bytes (×1024) for display; current usage is shown as-is. The mock quota backend uses the same units so behaviour matches real pyquota.

## Frontend (React 19 + Vite 7 + TypeScript 5)

- **Stack:** Mantine 8, Zod 4, Redux Toolkit, TanStack Query 5, axios, Vitest, ESLint.
- Build output is written to the backend `static/` folder so Flask can serve the SPA.

### Setup and build

```bash
cd frontend
npm install
npm run build    # writes to ../static
```

### Develop

```bash
cd frontend
npm run dev      # Vite dev server (proxy API to backend if needed)
```

### Test and lint

```bash
cd frontend
npm run test
npm run lint
```

## Project layout

- `app/` – Flask application (factory, routes, quota logic, Pydantic models, DB)
- `alembic/` – Database migrations
- `frontend/` – Vite + React SPA (builds into `static/`)
- `static/` – Served by Flask at `/` (index.html and assets)
- `run.py` – Entry point; creates app and runs dev server
- `config.json` – Master server config (not committed)
- `config.slave.json` – Slave server config (not committed)
