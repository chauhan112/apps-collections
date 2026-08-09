# Apps Docker Stack

Runs the whole platform as **one Docker Compose stack** with a single public
entry point:

```
                     host :8003
                         |
               +-------------------+
               |  apps-collection  |   <-- MAIN app (this repo, Flask gateway)
               +-------------------+
                  |
    /backend/*   |  (inter-service DNS on the compose network)
                  v
         +----------------+
         |    backend     |   <-- internal only
         | Django (gunic) |
         +----------------+
              :8500
         (no host port)
```

| service           | repo / dir                  | runner    | internal port | published |
|-------------------|-----------------------------|-----------|---------------|-----------|
| `apps-collection` | **this repo** (Flask)       | gunicorn  | 8003          | **yes** (`${APPS_PORT}`) |
| `backend`         | `chauhan112/backend`        | gunicorn  | `${BACKEND_PORT}` (8500) | no |

`apps-collection` is the **only** service with a host port. The Django `backend`
lives entirely inside the compose network and is reached by the gateway via the
service name (`http://backend:8500`).

The backend repo is **private**, so it is cloned on the host (with your SSH
keys) into `deploy/services/backend` and `COPY`ed into the image at build time.
**Nothing is cloned during the build.**

---

## Quick start

```bash
cd deploy

# 1. Clone the private repo and scaffold env files
./clone.sh

# 2. (optional) tweak ports/URLs in .env

# 3. Build and run the whole stack
docker compose up --build
```

After startup:

- Main app / gateway -> http://localhost:8003
- `/backend/*` is proxied to the internal `backend` service.

`apps-collection` waits for the `backend` healthcheck before starting, so the
proxy is ready when the gateway comes up.

---

## Files

```
<repo root>/
  .dockerignore              # slims the MAIN-app build context (excludes deploy/, .venv, ...)
  deploy/
    Dockerfile.apps          # MAIN app (Flask gateway)
    Dockerfile               # Django backend (APP_DIR, PYTHON_VERSION)
    docker-compose.yml       # 2 services; only `apps` is published
    docker-entrypoint.sh     # migrate -> collectstatic -> exec CMD  (backend)
    clone.sh                 # clone repo + scaffold env
    .dockerignore            # slims the backend build context
    .env.example             # APPS_PORT, BASE_URL, BACKEND_TARGET, BACKEND_PORT
    env/
      backend.env.example
    services/                # gitignored: hosts the cloned repo
```

---

## Configuration (`.env`)

| var             | default                          | meaning |
|-----------------|----------------------------------|---------|
| `APPS_PORT`     | `8003`                           | host port for the main gateway (also gunicorn bind) |
| `BASE_URL`      | `http://localhost:8003/apps`     | base URL prefix for app links on the index page |
| `BACKEND_TARGET`| `http://backend:8500`            | where `/backend/*` is proxied (internal) |
| `BACKEND_PORT`  | `8500`                           | port `backend` binds to **inside** the network (no host port). If changed, update `BACKEND_TARGET` to match |

Per-service container env: `env/backend.env` (copied from the `*.example`
template by `clone.sh`).

### Auto superuser

The `backend`'s `DJANGO_SUPERUSER_*` vars (in `env/backend.env`) create an admin
on startup — idempotently, so restarts never duplicate it:

```env
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=ChangeMeNow!
DJANGO_SUPERUSER_EMAIL=admin@example.com
```

Leave `DJANGO_SUPERUSER_USERNAME` blank to skip. The user lands in the backend's
own SQLite file (`data/backend.sqlite3`).

---

## Env review — what changed for Docker

### backend (`env/backend.env.example`)

The repo's `.env.sample` already works in Docker (`ALLOWED_HOSTS=*`, SQLite,
fully env-driven). The only addition is a **configurable port**
(`BACKEND_PORT`), which is now internal-only.

---

## Wiring with apps-collections

The gateway proxies `/backend/*` -> `BACKEND_TARGET` (set in `.env`). Since
`backend` is internal, that target uses the compose service name:

- `/backend/*` -> **`backend`** repo: `BACKEND_TARGET=http://backend:8500`

---

## Day-to-day

```bash
# rebuild after pulling the repo
git -C services/backend pull && docker compose up --build -d

# tails
docker compose logs -f apps
docker compose logs -f backend

# exec into the internal backend (it has no host port)
docker compose exec backend python manage.py createsuperuser

# stop
docker compose down
```

### Notes / caveats

- The backend has its **own** persistent SQLite file on the host
  (`deploy/data/backend.sqlite3`). It survives `down`/`up` and container
  recreation; `clone.sh` pre-creates the empty file. Delete it to reset the DB.
- `appsDeployed/` (the built frontends) is part of **this** repo's build context,
  so it is baked into the `apps-collection` image. Rebuild the gateway after
  deploying a new frontend.
