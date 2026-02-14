# Quota Manager (qman)

Quota management UI: master aggregates quotas from slave hosts; slaves expose local quota data via a remote API.

## Backend (Python 3.11+)

- **Stack:** Flask 3+, Pydantic 2+, SQLAlchemy 2, Alembic, gunicorn
- **Config:** Use `config.json` for the master server and `config.slave.json` for the slave server. Copy from `config.master_example.json` and `config.slave_example.json` and adjust.
- **Auth:** OAuth via the `auth_connect` submodule (`git submodule update --init`). The submodule includes a minimal mock OAuth server for local development.

### Mock OAuth server (development)

The mock server lives in the `auth_connect` submodule and implements the endpoints expected by the client. It loads mock users, groups, and clients from `oauth.mock.config.json` at the project root. Use it when `oauth.config.json` points at `server.url: "http://localhost:8077"`.

```bash
# Terminal 1: run mock OAuth server (port 8077) from project root
python auth_connect/mock_oauth_server.py

# Terminal 2: run app with OAuth enabled
# In oauth.config.json set "enabled": true and "server": {"url": "http://localhost:8077", ...}
python app.py
```

Optional env: `MOCK_OAUTH_PORT`, `MOCK_OAUTH_CLIENT_ID`, `MOCK_OAUTH_CLIENT_SECRET`, `MOCK_OAUTH_REDIRECT_URL`. Default client matches `auth_connect/oauth.config.example.json` (id=1, secret=someLongSecret). Connect URL supports `?user_id=1` or `?user_id=2` to log in as Mock Admin or Mock User.

**Full local dev stack (mock OAuth + master + slave mock + frontend):** Run these in separate terminals (or use the script below). In `oauth.config.json` set `enabled: true`, `server.url: "http://localhost:8077"`, and `client.url: "http://localhost:5173"` so the frontend dev server receives the OAuth callback.

| Terminal | Command                                       | Port |
|----------|-----------------------------------------------|------|
| 1 | `python auth_connect/mock_oauth_server.py`    | 8077 |
| 2 | `CONFIG_PATH=config.slave.json python app.py` | 8437 (slave, mock quota) |
| 3 | `python app.py`                               | 8436 (master) |
| 4 | `cd frontend && npm run dev`                  | 5173 |

Then open http://localhost:5173. Log in via the mock OAuth connect page; use a user from `oauth.mock.config.json` (e.g. **alice** for "My usage" only, **charlie** for admin and "Manage"). Alternatively run `./scripts/dev.sh` from the project root to start all four processes (mock OAuth, slave, master, frontend) in the background.

### Setup

```bash
conda create -n qman python=3.11  # or use existing env named qman
conda activate qman
pip install -r requirements.txt
cp config.master_example.json config.json
cp config.slave_example.json config.slave.json
```

### Database (SQLite dev / PostgreSQL prod)

- Development uses SQLite: `sqlite:///qman.sqlite` (or set `DATABASE_URL`).
- Run migrations: `alembic upgrade head`.
- For production, set `DATABASE_URL` to your PostgreSQL URL.

### Run

**Master server** (uses `config.json`):

```bash
python app.py   # serves on http://localhost:8436
# Production: gunicorn -w 4 -b 0.0.0.0:8436 "server:app"
```

**Slave server** (uses `config.slave.json`):

```bash
CONFIG_PATH=config.slave.json python app.py
# Production: CONFIG_PATH=config.slave.json gunicorn -w 4 -b 0.0.0.0:8436 "server:app"
```

**Slave in mock mode** (no pyquota; uses in-memory mock host with sample filesystems and users): set `"MOCK_QUOTA": true` in `config.slave.json`, then run the slave as above. The mock host includes several devices (e.g. `/dev/sda1`, `/dev/sdb1`, `/dev/nvme0n1p1`), users (alice, bob, charlie, …), and quota limits so you can test the UI without real quota support.

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
- `app.py` – Entry point; creates app and runs dev server
- `config.json` – Master server config (not committed)
- `config.slave.json` – Slave server config (not committed)
