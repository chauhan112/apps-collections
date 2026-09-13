# apps-collection

Flask gateway that serves the app index, hosts deployed frontends under `/apps/`,
and reverse-proxies `/backend/*` to the Django **backend**, which — like its
PostgreSQL database — runs independently of this repo.

## Architecture

```
                host :8003  (systemd: app-center.service, bare gunicorn)
                    |
          +---------------------+
          |   apps-collection   |   Flask gateway (this repo)
          +---------------------+
                    |  /backend/*   -> BACKEND_TARGET from .env (default http://127.0.0.1:8500)
                    v
          +---------------------+
          |      backend        |   Django + gunicorn (independent, own repo/deploy)
          +---------------------+
                    |  DATABASE_*  -> 127.0.0.1:5433
                    v
          +---------------------+
          |  backend-postgres   |   PostgreSQL 17 (independent, ../backend-db)
          +---------------------+
```

| piece              | repo / dir                   | role                     | port      |
|--------------------|------------------------------|--------------------------|-----------|
| `apps`             | **this repo** (Flask)        | gateway + frontend host  | `:8003` (systemd `app-center.service`) |
| `backend`          | `chauhan112/backend`         | Django REST API          | `:8500` (run independently) |
| `backend-postgres` | `../backend-db`              | PostgreSQL 17            | `:5433` (published; 5432 taken by lobehub) |

## Run (systemd)

The app runs as a bare host process via `app-center.service` (kept in this repo,
installed into `/etc/systemd/system/`). No container involved.

```bash
# install / update after editing the unit
sudo cp ~/timeline/global/apps-server/app-center.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now app-center

# day-to-day via the bashrc sys-* helpers (pm2-style)
sys-ls
sys-status center
sys-logs center
sys-restart center
```

Once running:

- Gateway / index -> http://localhost:8003
- Deployed frontend -> http://localhost:8003/apps/<name>/
- Backend API (via proxy) -> http://localhost:8003/backend/api/...
  e.g. http://localhost:8003/backend/api/doa/openapi.json
- Backend admin -> http://localhost:8003/backend/admin/

The backend itself and its database are started from their own locations:

```bash
# PostgreSQL (~/timeline/global/backend-db)
cd ~/timeline/global/backend-db && docker compose up -d

# Backend (~/timeline/global/backend) - systemd app-backend.service
sudo cp ~/timeline/global/backend/app-backend.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now app-backend
```

## Backend reverse proxy

Requests to `/backend/*` are forwarded to the Django backend with the `/backend`
prefix stripped, so frontends can call the API same-origin:

- `/backend/api/doa/activities/read_all` -> backend `/api/doa/activities/read_all`

All HTTP methods (GET/POST/PUT/PATCH/DELETE/OPTIONS) are proxied; body, query
string, and headers are forwarded (hop-by-hop headers dropped). An unreachable
backend yields `502`. The target comes from `BACKEND_TARGET` in `.env`
(default `http://127.0.0.1:8500`).

## Deploy a frontend

One task clones a repo, builds it with Bun, copies the build into `appsDeployed/`,
and registers a card on the index:

```bash
invoke deploy --repo git@github.com:chauhan112/Tasks-Frontend.git --name Tasks-Frontend
```

Flags: `--title`, `--description`, `--backend-url` (default `/backend`),
`--no-register`. The app is served at `/apps/<name>/`; `apps.json` is read at
page load, so no restart is needed. Run `invoke --list` for the granular
`setup`/`build`/`deploy` tasks. A frontend should set `VITE_BACKEND_URL=/backend`
so requests route through the proxy.

## Configuration (`.env`)

| var              | default                       | meaning |
|------------------|-------------------------------|---------|
| `BASE_URL`       | `/apps`                       | base URL prefix for index links |
| `BACKEND_TARGET` | `http://127.0.0.1:8500`       | where `/backend/*` is proxied |
| `CORS_ORIGINS`   | `*`                           | allowed origins (comma-separated allowlist, or `*`) |
