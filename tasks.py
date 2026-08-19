import json
import shutil
from pathlib import Path

from invoke import task

TEMP_DIR = Path("temp")
APPS_DIR = Path("appsDeployed")
APPS_JSON = Path("apps.json")

# --- Docker backend stack (deploy/ ships in this repo) ---
DEPLOY_DIR = Path("deploy")
SERVICES_DIR = DEPLOY_DIR / "services"
DATA_DIR = DEPLOY_DIR / "data"
ENV_DIR = DEPLOY_DIR / "env"
BACKEND_REPO = "git@github.com:chauhan112/backend.git"
BACKEND_DIR = SERVICES_DIR / "backend"
BACKEND_ENV = ENV_DIR / "backend.env"
BACKEND_SQLITE = DATA_DIR / "backend.sqlite3"


@task(
    help={
        "repo": "Git URL of the Vite frontend to clone",
        "name": "Folder name under temp/ to clone into",
        "backend-url": "Value for VITE_BACKEND_URL (the apps-center /backend reverse-proxy prefix)",
    }
)
def setup(c, repo="git@github.com:chauhan112/Tasks-Frontend.git", name="Tasks-Frontend", backend_url="/backend"):
    """Clone a Vite frontend into temp/<name> and write its .env for the /backend proxy.

    Requests made by the built app go to <backend-url>/api/... , which the
    apps-center /backend reverse proxy strips and forwards to the Django backend
    (e.g. /backend/api/tasks/... -> Django /api/tasks/...).
    """
    target = TEMP_DIR / name
    TEMP_DIR.mkdir(exist_ok=True)

    # Fresh clone so the task is repeatable
    if target.exists():
        c.run(f"rm -rf {target}")

    c.run(f"git clone {repo} {target}")

    env_content = (
        "# Served behind the apps-center /backend reverse proxy.\n"
        f"VITE_BACKEND_URL={backend_url}\n"
    )
    (target / ".env").write_text(env_content)
    print(f"[setup] Wrote {target}/.env with VITE_BACKEND_URL={backend_url}")


def _unique_deploy_name(name):
    """Return a free folder name under appsDeployed/, appending _2, _3, ... if taken.

    Note: this collision handling is for the deploy target only. The temp clone
    folder is always overwritten fresh.
    """
    candidate = APPS_DIR / name
    if not candidate.exists():
        return name
    n = 2
    while (APPS_DIR / f"{name}_{n}").exists():
        n += 1
    return f"{name}_{n}"


def _register_app(title, description, deploy_name):
    """Add/update an entry in apps.json so the index card points to the latest deploy.

    Matched by title, so re-deploys (which create a _2, _3 suffix in
    appsDeployed/) keep a single card that always points to the newest version.
    """
    data = json.loads(APPS_JSON.read_text()) if APPS_JSON.exists() else []
    url = f"/{deploy_name}"
    for entry in data:
        if entry.get("name") == title:
            entry["url"] = url
            if description:
                entry["description"] = description
            APPS_JSON.write_text(json.dumps(data, indent=4) + "\n")
            print(f"[register] Updated '{title}' -> {url}")
            return
    data.append({"name": title, "description": description, "url": url})
    APPS_JSON.write_text(json.dumps(data, indent=4) + "\n")
    print(f"[register] Added '{title}' -> {url}")


@task(help={"name": "Folder name under temp/ to build"})
def _build(c, name="Tasks-Frontend"):
    """Run bun install + bun run build for the Vite app in temp/<name>."""
    target = TEMP_DIR / name
    if not target.exists():
        raise SystemExit(f"[build] {target} does not exist. Run `invoke setup` first.")

    with c.cd(str(target)):
        c.run("bun install")
        c.run("bun run build")

    dist = target / "dist"
    if not dist.exists():
        raise SystemExit(f"[build] expected build output at {dist} but it is missing")
    print(f"[build] Built {dist}")


@task(
    help={
        "repo": "Git URL of the Vite frontend to clone",
        "name": "Folder name under temp/ to clone into AND appsDeployed/ to deploy to",
        "backend-url": "Value for VITE_BACKEND_URL (the apps-center /backend reverse-proxy prefix)",
        "title": "Display name for the index card (defaults to a prettified name)",
        "description": "Card description text",
        "register": "Add/update an entry in apps.json so the app shows on the index (default: true)",
    }
)
def deploy(c, repo="git@github.com:chauhan112/Tasks-Frontend.git", name="Tasks-Frontend", backend_url="/backend",
           title="", description="", register=True):
    """One-shot: clone + .env + bun install + build, then move dist/ to appsDeployed/<name>.

    If appsDeployed/<name> already exists, a _2, _3, ... suffix is used so prior
    deploys are never overwritten. Prints the final served URL.
    """
    setup(c, repo=repo, name=name, backend_url=backend_url)
    _build(c, name=name)

    dist = TEMP_DIR / name / "dist"
    deploy_name = _unique_deploy_name(name)
    dest = APPS_DIR / deploy_name
    APPS_DIR.mkdir(exist_ok=True)
    shutil.copytree(dist, dest)

    print(f"[deploy] Moved {dist} -> {dest}")
    print(f"[deploy] Served at /apps/{deploy_name}/")

    if register:
        card_title = title or name.replace("-", " ").replace("_", " ").strip()
        _register_app(card_title, description, deploy_name)


@task(
    help={
        "repo": "Git URL of the Django backend to clone",
        "up": "Bring the stack up after building (default: true)",
        "no-cache": "Build the image without the Docker layer cache",
        "remove-orphans": "Remove stale containers on up (default: true)",
    }
)
def deploy_backend(c, repo=BACKEND_REPO, up=True, no_cache=False, remove_orphans=True):
    """Refetch the backend service clean and (re)build its Docker container.

    Mirrors the frontend `deploy` flow for the backend: wipe services/backend,
    git clone it fresh, scaffold env/SQLite if missing (existing files are kept),
    then docker compose build the backend image (and optionally `up -d`).
    """
    # 1. Clean: remove the existing clone so we refetch fresh.
    if BACKEND_DIR.exists():
        c.run(f"rm -rf {BACKEND_DIR}")
        print(f"[deploy-backend] Removed {BACKEND_DIR}")

    # 2. Fresh clone.
    SERVICES_DIR.mkdir(parents=True, exist_ok=True)
    c.run(f"git clone {repo} {BACKEND_DIR}")
    print(f"[deploy-backend] Cloned {repo} -> {BACKEND_DIR}")

    # 3. Scaffold env + SQLite if missing (never clobber existing secrets/data).
    ENV_DIR.mkdir(parents=True, exist_ok=True)
    if not BACKEND_ENV.exists() and (ENV_DIR / "backend.env.example").exists():
        c.run(f"cp {ENV_DIR / 'backend.env.example'} {BACKEND_ENV}")
        print(f"[deploy-backend] Seeded {BACKEND_ENV} from example")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not BACKEND_SQLITE.exists():
        BACKEND_SQLITE.touch()
        print(f"[deploy-backend] Created {BACKEND_SQLITE}")

    # 4. Build the backend container, then bring the stack up.
    with c.cd(str(DEPLOY_DIR)):
        build_cmd = "docker compose build backend" + (" --no-cache" if no_cache else "")
        c.run(build_cmd)
        print("[deploy-backend] Built backend image")
        if up:
            up_cmd = "docker compose up -d" + (" --remove-orphans" if remove_orphans else "")
            c.run(up_cmd)
            print("[deploy-backend] Stack is up -> http://localhost:8003")


# inv deploy -r git@github.com:chauhan112/Notes-frontend.git -n "notes" --no-register

# inv deploy -r git@github.com:chauhan112/Tasks-Frontend.git -n "nested-tasks" --no-register

# inv deploy -r git@github.com:chauhan112/Scheduler-frontend.git -n "schedular" --no-register

# inv deploy -r git@github.com:chauhan112/ai-chats-frontend.git -n "ai-chats" --no-register

# inv deploy -r git@github.com:chauhan112/doa-frontend-react.git -n "doa" --no-register


# inv deploy -r git@github.com:chauhan112/scanner-frontend.git -n "scanner" --no-register
