# apps-server

Flask app that serves the app index, deploys frontends under `/apps/`, and reverse-proxies API calls to the Django backend.

## Backend reverse proxy

Any request to `/backend/*` is forwarded to the Django backend (`any-backend` on `http://127.0.0.1:8500`), with the `/backend` prefix stripped:

- `/backend/api/tasks/read_all` -> Django `/api/tasks/read_all`

This lets deployed frontends call the API via a same-origin relative path. The target is configurable via `BACKEND_TARGET` in `.env` (see `.env.sample`).

All HTTP methods (GET/POST/PUT/PATCH/DELETE/OPTIONS) are proxied. Body, query string, and headers are forwarded; hop-by-hop headers are dropped. If the backend is unreachable, the proxy returns `502`.

## Deploy a Vite + Bun frontend

One command clones a repo, builds it with Bun, copies the build into `appsDeployed/`, and registers it on the index page:

```bash
invoke deploy --repo git@github.com:chauhan112/Tasks-Frontend.git --name Tasks-Frontend
```

Options:

- `--repo`           Git URL to clone
- `--name`           Folder name (used for the temp clone and `appsDeployed/<name>`)
- `--title`          Display name on the index card (defaults to a prettified `--name`)
- `--description`    Card description text
- `--backend-url`    Value written to the app's `.env` as `VITE_BACKEND_URL` (default `/backend`)
- `--no-register`    Deploy without adding a card to the index

Behavior:

- Fresh clone each run into `temp/<name>`.
- Build output (`dist/`) is copied to `appsDeployed/<name>`. If that folder exists, a `_2`, `_3`, ... suffix is used so prior deploys are never overwritten.
- An entry is added/updated in `apps.json` (matched by title) so the index card always points to the latest deploy. No restart needed — `apps.json` is read at page load.
- The app is then served at `/apps/<name>/`.

### Frontend backend URL

A frontend should point its API base at `/backend` so requests route through the proxy. The deploy task writes this to the app's `.env`:

```
VITE_BACKEND_URL=/backend
```

The frontend then builds URLs as `${VITE_BACKEND_URL}/api/...`, e.g. `/backend/api/tasks/read_all`.

### Granular steps

The same pipeline is available as separate tasks:

```bash
invoke setup --repo <url> --name <name>   # clone into temp/ and write .env
invoke build  --name <name>               # bun install && bun run build
invoke deploy --repo <url> --name <name>  # setup + build + move + register
```
