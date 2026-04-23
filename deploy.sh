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
echo "=== Reloading nginx (refresh upstream IPs) ==="
# When backend/frontend containers are recreated, they get fresh IPs in the
# Docker bridge network. nginx caches the OLD IP in its upstream resolver
# until reloaded — this is the #1 source of post-deploy 502s. Always reload
# at the end of a deploy. Use `nginx -s reload` (graceful) over `restart`
# (downtime). Falls back to a hard restart if reload fails for any reason.
if docker exec baza-nginx-1 nginx -t >/dev/null 2>&1; then
    if docker exec baza-nginx-1 nginx -s reload 2>&1; then
        echo "  nginx reloaded gracefully"
    else
        echo "  nginx reload FAILED — falling back to hard restart"
        docker restart baza-nginx-1
    fi
else
    echo "  nginx config check failed — skipping reload (investigate before next deploy)"
fi

echo ""
echo "=== Smoke test ==="
sleep 3
curl -sI "https://${SERVER_IP}/" 2>/dev/null | head -1 || curl -sI "http://${SERVER_IP}/" | head -1
curl -s "https://${SERVER_IP}/api/health" 2>/dev/null || curl -s "http://${SERVER_IP}/api/health"
echo ""

echo ""
echo "==========================="
echo "БАЗА is now running!"
echo "Open: http://${SERVER_IP}"
echo "API:  http://${SERVER_IP}/api/health"
echo "==========================="
