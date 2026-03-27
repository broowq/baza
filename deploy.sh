#!/bin/bash
set -euo pipefail

echo "=== БАЗА Deploy Script ==="
echo ""

# Check if .env.production exists
if [ ! -f .env.production ]; then
    echo "ERROR: .env.production not found!"
    echo "Copy .env.production.example to .env.production and fill in values:"
    echo "  cp .env.production.example .env.production"
    echo "  nano .env.production"
    exit 1
fi

# Load env vars
set -a
source .env.production
set +a

# Check SERVER_IP is set
if [ "${SERVER_IP:-}" = "YOUR_SERVER_IP" ] || [ -z "${SERVER_IP:-}" ]; then
    echo "ERROR: SERVER_IP is not set in .env.production"
    echo "Set it to your server's public IP address."
    exit 1
fi

# Generate secrets if still default
if [ "${SECRET_KEY:-}" = "generate-with-openssl-rand-hex-32" ]; then
    echo "Generating SECRET_KEY..."
    NEW_SECRET=$(openssl rand -hex 32)
    sed -i'' -e "s/generate-with-openssl-rand-hex-32/$NEW_SECRET/" .env.production
fi

if [ "${POSTGRES_PASSWORD:-}" = "generate-strong-password" ]; then
    echo "Generating POSTGRES_PASSWORD..."
    NEW_PG_PASS=$(openssl rand -hex 16)
    sed -i'' -e "s/POSTGRES_PASSWORD=generate-strong-password/POSTGRES_PASSWORD=$NEW_PG_PASS/" .env.production
fi

if [ "${REDIS_PASSWORD:-}" = "generate-strong-password" ]; then
    echo "Generating REDIS_PASSWORD..."
    NEW_REDIS_PASS=$(openssl rand -hex 16)
    sed -i'' -e "s/REDIS_PASSWORD=generate-strong-password/REDIS_PASSWORD=$NEW_REDIS_PASS/" .env.production
fi

# Reload after potential changes
set -a
source .env.production
set +a

echo ""
echo "Server IP: ${SERVER_IP}"
echo ""

echo "Building and starting services..."
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build

echo ""
echo "Waiting for services to start..."
sleep 10

echo ""
echo "=== Service Status ==="
docker compose -f docker-compose.prod.yml ps

echo ""
echo "=== Running database migrations ==="
docker compose -f docker-compose.prod.yml exec -T backend alembic upgrade head 2>/dev/null || echo "Migrations skipped (alembic not configured or already up to date)"

echo ""
echo "==========================="
echo "БАЗА is now running!"
echo "Open: http://${SERVER_IP}"
echo "API:  http://${SERVER_IP}/api/health"
echo "==========================="
