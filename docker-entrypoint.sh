#!/bin/sh
set -e

echo "[entrypoint] initializing database..."
flask init-db

echo "[entrypoint] seeding demo data (idempotent)..."
flask seed

echo "[entrypoint] starting gunicorn on :8000..."
exec gunicorn --bind 0.0.0.0:8000 --workers 2 --access-logfile - --error-logfile - wsgi:app
