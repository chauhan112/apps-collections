#!/bin/sh
# Shared entrypoint for both Django backends.
#   1. migrate
#   2. collectstatic (best-effort)
#   3. create superuser from DJANGO_SUPERUSER_* env (idempotent)
#   4. exec the service command (runserver / gunicorn) from docker-compose.yml
set -e

echo "[entrypoint] Running migrations..."
python manage.py migrate --noinput

echo "[entrypoint] Collecting static files (best-effort)..."
# Not every project defines STATIC_ROOT, so treat failure as non-fatal.
python manage.py collectstatic --noinput || echo "[entrypoint] collectstatic skipped"

echo "[entrypoint] Ensuring superuser..."
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
  # Idempotent: only creates the user if it doesn't already exist.
  # Reads credentials from the environment (no shell interpolation into Python).
  python manage.py shell <<'PY' || echo "[entrypoint] superuser setup failed (continuing)"
import os
from django.contrib.auth import get_user_model
User = get_user_model()
username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "")
email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
if not password:
    print("[entrypoint] DJANGO_SUPERUSER_PASSWORD empty; skipping")
elif User.objects.filter(username=username).exists():
    print(f"[entrypoint] superuser '{username}' already exists")
else:
    User.objects.create_superuser(username, email, password)
    print(f"[entrypoint] superuser '{username}' created")
PY
else
  echo "[entrypoint] DJANGO_SUPERUSER_USERNAME not set; skipping superuser"
fi

echo "[entrypoint] Starting: $*"
exec "$@"
