#!/usr/bin/env sh
# Clone the private backend into ./services and prepare env files.
# Requires SSH access to github.com:chauhan112 (host SSH keys).
set -e
cd "$(dirname "$0")"

echo "==> Cloning backend -> services/backend"
[ -d services/backend ] || git clone git@github.com:chauhan112/backend.git services/backend

echo "==> Preparing env files"
[ -f env/backend.env ]         || cp env/backend.env.example env/backend.env
[ -f .env ]                    || cp .env.example .env

echo "==> Preparing persistent SQLite file"
# Bind-mounted host file must exist before `up`, or Docker mounts a directory.
mkdir -p data
[ -f data/backend.sqlite3 ]    || touch data/backend.sqlite3

cat <<'EOF'

Done. Next steps:
  1. (optional) Edit .env -> change BACKEND_PORT (default 8500).
  2. Build & run:
       docker compose up --build
EOF
