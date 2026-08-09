# apps-collection

Flask gateway that serves the app index, hosts deployed frontends under `/apps/`,
and reverse-proxies API traffic to an internal Django **backend**. Runs as a
single Docker Compose stack with one public entry point.

## Architecture

```
                host :8003
                    |
          +---------------------+
          |   apps-collection   |   Flask gateway (this repo) -- ONLY public service
          +---------------------+
                    |  /backend/*   (compose network DNS)
                    v
          +---------------------+
          |       backend       |   Django + gunicorn  (internal only, :8500)
          +---------------------+
```

| service   | image / repo          | role                    | port    | published |
|-----------|-----------------------|-------------------------|---------|-----------|
| `apps`    | **this repo** (Flask) | gateway + frontend host | `:8003` | **yes**   |
| `backend` | `chauhan112/backend`  | Django REST API         | `:8500` | no        |

`apps` is the only service with a host port. `backend` lives inside the compose
network and is reached by the gateway via the service name (`http://backend:8500`).
The private backend repo is cloned on the host and `COPY`ed into the image at
build time — nothing is cloned during the build.

## Build & run with Docker Compose

```bash
cd deploy

# 1. Clone the private backend repo + scaffold env files and the SQLite DB
./clone.sh

# 2. (optional) tweak ports/URLs
cp .env.example .env && $EDITOR .env

# 3. Build the images and start the stack (detached)
docker compose up -d --build
```

The gateway waits for `backend` to pass its healthcheck before starting, so the
proxy is ready when it comes up. Once running:

- Gateway / index -> http://localhost:8003
- Deployed frontend -> http://localhost:8003/apps/<name>/
- Backend API (via proxy) -> http://localhost:8003/backend/api/...
  e.g. http://localhost:8003/backend/api/doa/openapi.json
- Backend admin -> http://localhost:8003/backend/admin/

### Day-to-day

```bash
cd deploy
docker compose ps                                   # status (look for "healthy")
docker compose logs -f apps backend                 # tails
docker compose exec backend python manage.py shell  # shell into the backend

# rebuild after pulling the backend repo
git -C services/backend pull && docker compose up -d --build

docker compose down                  # stop  (deploy/data/backend.sqlite3 persists)
docker compose down --remove-orphans # also clears any stale containers
```

> Full ops reference (env vars, Dockerfile, healthchecks, per-service config) is
> in [`deploy/README.md`](deploy/README.md).

## Backend reverse proxy

Requests to `/backend/*` are forwarded to the Django backend with the `/backend`
prefix stripped, so frontends can call the API same-origin:

- `/backend/api/doa/activities/read_all` -> backend `/api/doa/activities/read_all`

All HTTP methods (GET/POST/PUT/PATCH/DELETE/OPTIONS) are proxied; body, query
string, and headers are forwarded (hop-by-hop headers dropped). An unreachable
backend yields `502`. The target is configurable via `BACKEND_TARGET` (default
`http://backend:8500`) in `deploy/.env`.

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
so requests route through the proxy. Rebuild the gateway image after deploying a
new frontend (`appsDeployed/` is part of its build context).

## Configuration

| var              | default                      | meaning |
|------------------|------------------------------|---------|
| `APPS_PORT`      | `8003`                       | gateway host port (also gunicorn bind) |
| `BASE_URL`       | `http://localhost:8003/apps` | base URL prefix for index links |
| `BACKEND_TARGET` | `http://backend:8500`        | where `/backend/*` is proxied (internal) |
| `BACKEND_PORT`   | `8500`                       | port `backend` binds to inside the network |
| `CORS_ORIGINS`   | `*`                          | allowed origins for the gateway (comma-separated allowlist, or `*`) |

Per-service container env lives in `deploy/env/backend.env` (template:
`deploy/env/backend.env.example`). A backend superuser is auto-created on startup
from the `DJANGO_SUPERUSER_*` vars.
