#!/bin/bash
set -e

echo "Waiting for PostgreSQL to become ready..."
until pg_isready -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-lead}" -q; do
    echo "PostgreSQL is not ready yet, retrying in 2s..."
    sleep 2
done
echo "PostgreSQL is ready."

echo "Running database migrations..."
alembic upgrade head
echo "Migrations complete."

echo "Starting application..."
exec "$@"
