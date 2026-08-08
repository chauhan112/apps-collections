#!/usr/bin/env sh
# Clone both private backends into ./services and prepare env files.
# Requires SSH access to github.com:chauhan112 (host SSH keys).
set -e
cd "$(dirname "$0")"

# generic-backend's handlers/githubHandler.py imports rlib.useful.SearchSystem
# at URL-load time, so the rlib submodule MUST be initialized or the app
# crashes on boot. --recurse-submodules pulls it (private; uses host SSH keys).
echo "==> Cloning generic-backend (+rlib submodule) -> services/generic-backend"
[ -d services/generic-backend ] || git clone --recurse-submodules git@github.com:chauhan112/generic-backend.git services/generic-backend

echo "==> Cloning backend -> services/backend"
[ -d services/backend ] || git clone git@github.com:chauhan112/backend.git services/backend

echo "==> Preparing env files"
[ -f env/generic-backend.env ] || cp env/generic-backend.env.example env/generic-backend.env
[ -f env/backend.env ]         || cp env/backend.env.example env/backend.env
[ -f .env ]                    || cp .env.example .env

echo "==> Preparing persistent SQLite files (one per backend, NOT shared)"
# Bind-mounted host files must exist before `up`, or Docker mounts a directory.
mkdir -p data
[ -f data/generic-backend.sqlite3 ] || touch data/generic-backend.sqlite3
[ -f data/backend.sqlite3 ]         || touch data/backend.sqlite3

cat <<'EOF'

Done. Next steps:
  1. Edit env/generic-backend.env -> set DIRECTUS_API_KEY.
  2. (optional) Edit .env -> change BACKEND_PORT (default 8500).
  3. Build & run both backends:
       docker compose up --build
EOF
