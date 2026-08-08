# Apps Docker Stack

Runs the whole platform as **one Docker Compose stack** with a single public
entry point:

```
                    host :8003
                        |
              +-------------------+
              |  apps-collection  |   <-- MAIN app (this repo, Flask gateway)
              +-------------------+
                 |              |
   /backend/*   |              |  (inter-service DNS on the compose network)
                 v              v
        +----------------+   +------------------+
        |    backend     |   | generic-backend  |   <-- internal only
        | Django (gunic) |   | Django (runserver|
        +----------------+   +------------------+
             :8500                  :8000
        (no host port)         (no host port)
```

| service           | repo / dir                  | runner    | internal port | published |
|-------------------|-----------------------------|-----------|---------------|-----------|
| `apps-collection` | **this repo** (Flask)       | gunicorn  | 8003          | **yes** (`${APPS_PORT}`) |
| `backend`         | `chauhan112/backend`        | gunicorn  | `${BACKEND_PORT}` (8500) | no |
| `generic-backend` | `chauhan112/generic-backend`| runserver | 8000          | no |

`apps-collection` is the **only** service with a host port. The two Django
backends live entirely inside the compose network and are reached by the gateway
via service names (`http://backend:8500`, `http://generic-backend:8000`).

The backend repos are **private**, so they are cloned on the host (with your SSH
keys) into `deploy/services/<repo>` and `COPY`ed into the images at build time.
**Nothing is cloned during the build.**

---

## Quick start

```bash
cd deploy

# 1. Clone both private repos (+ rlib submodule) and scaffold env files
./clone.sh

# 2. Put your real Directus key in env/generic-backend.env
#    (optional) tweak ports/URLs in .env

# 3. Build and run the whole stack
docker compose up --build
```

After startup:

- Main app / gateway -> http://localhost:8003
- `/backend/*` is proxied to the internal `backend` service.

`apps-collection` waits for both backends' healthchecks before starting, so the
proxy is ready when the gateway comes up.

---

## Files

```
<repo root>/
  .dockerignore              # slims the MAIN-app build context (excludes deploy/, .venv, ...)
  deploy/
    Dockerfile.apps          # MAIN app (Flask gateway)
    Dockerfile               # shared by both Django backends (APP_DIR, PYTHON_VERSION)
    docker-compose.yml       # 3 services; only `apps` is published
    docker-entrypoint.sh     # migrate -> collectstatic -> exec CMD  (backends)
    clone.sh                 # clone repos (+rlib) + scaffold env
    .dockerignore            # slims the backends build context
    .env.example             # APPS_PORT, BASE_URL, BACKEND_TARGET, BACKEND_PORT
    env/
      generic-backend.env.example
      backend.env.example
    services/                # gitignored: hosts the cloned repos
```

---

## Configuration (`.env`)

| var             | default                          | meaning |
|-----------------|----------------------------------|---------|
| `APPS_PORT`     | `8003`                           | host port for the main gateway (also gunicorn bind) |
| `BASE_URL`      | `http://localhost:8003/apps`     | base URL prefix for app links on the index page |
| `BACKEND_TARGET`| `http://backend:8500`            | where `/backend/*` is proxied (internal). Set `http://generic-backend:8000` to route to generic-backend |
| `BACKEND_PORT`  | `8500`                           | port `backend` binds to **inside** the network (no host port). If changed, update `BACKEND_TARGET` to match |

Per-service container env: `env/generic-backend.env` and `env/backend.env`
(copied from the `*.example` templates by `clone.sh`).

### Auto superuser

Each backend's `DJANGO_SUPERUSER_*` vars (in its `env/*.env`) create an admin
on startup — idempotently, so restarts never duplicate it:

```env
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=ChangeMeNow!
DJANGO_SUPERUSER_EMAIL=admin@example.com
```

Leave `DJANGO_SUPERUSER_USERNAME` blank to skip. The user lands in that backend's
own SQLite file (e.g. `data/backend.sqlite3`).

---

## Env review — what changed for Docker

### generic-backend (`env/generic-backend.env.example`)

The repo's `env.sample` is dev-localhost-only and needs changes in a container:

| var                  | repo default        | docker value             | why |
|----------------------|---------------------|--------------------------|-----|
| `ALLOWED_HOSTS`      | `127.0.0.1`         | `*`                      | requests arrive via the Docker network / proxy |
| `CORS_ALLOWED_ORIGINS` | `localhost:3000`  | frontends + apps origin  | so frontends can call the API |
| `DIRECTUS_API_KEY`   | `***` placeholder   | **your real key**        | app reads data through Directus |

The OIDC block (`OIDC_ISSUER`, `OIDC_RSA_PRIVATE_KEY_PATH`) is **optional** and
left commented: the app runs without an `oidc.key`.

### backend (`env/backend.env.example`)

The repo's `.env.sample` already works in Docker (`ALLOWED_HOSTS=*`, SQLite,
fully env-driven). The only addition is a **configurable port**
(`BACKEND_PORT`), which is now internal-only.

---

## Runtime gotchas (already handled in the build)

- **rlib is required at startup.** Despite being a submodule, `handlers/githubHandler.py`
  imports `rlib.useful.SearchSystem` during URL load, so `generic-backend` will
  not boot without it. `clone.sh` uses `--recurse-submodules` to fetch it.
- **gitpython needs the `git` binary.** `generic-backend` imports gitpython at
  startup, so the backend image installs `git`.

---

## Wiring with apps-collections

The gateway already proxies `/backend/*` -> `BACKEND_TARGET` (set in `.env`).
Because both backends are internal, that target uses the compose service name:

- `/backend/*` -> **`backend`** repo: `BACKEND_TARGET=http://backend:8500`
- `/backend/*` -> **`generic-backend`**: `BACKEND_TARGET=http://generic-backend:8000`

---

## Day-to-day

```bash
# rebuild after pulling a repo
git -C services/generic-backend pull --recurse-submodules && docker compose up --build -d

# tails
docker compose logs -f apps
docker compose logs -f backend
docker compose logs -f generic-backend

# exec into an internal backend (it has no host port)
docker compose exec backend python manage.py createsuperuser

# stop
docker compose down
```

### Notes / caveats

- `generic-backend` runs via Django's `runserver` (the repo ships **no gunicorn**).
  Fine for dev; add `gunicorn` to its deps if you want prod WSGI.
- Each backend has its **own** persistent SQLite file on the host
  (`deploy/data/generic-backend.sqlite3`, `deploy/data/backend.sqlite3`) — the two
  are **never shared** (different schemas). They survive `down`/`up` and
  container recreation; `clone.sh` pre-creates the empty files. Delete them to
  reset a DB.
- `appsDeployed/` (the built frontends) is part of **this** repo's build context,
  so it is baked into the `apps-collection` image. Rebuild the gateway after
  deploying a new frontend.
