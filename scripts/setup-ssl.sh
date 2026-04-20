#!/usr/bin/env bash
# setup-ssl.sh — one-shot script to enable HTTPS on prod via Let's Encrypt.
#
# What it does (idempotent, safe to re-run):
#   1. Creates `.env → .env.production` symlink (silences docker compose WARNs)
#   2. Obtains TLS certificate for usebaza.ru + www.usebaza.ru via certbot webroot
#      (uses already-running nginx :80 + /.well-known/acme-challenge location)
#   3. Swaps nginx config to the HTTPS version and reloads nginx
#   4. Installs a weekly cron job that runs `certbot renew` + reloads nginx
#
# Preconditions:
#   - DNS A/AAAA records for usebaza.ru and www.usebaza.ru point to this server
#   - Run from /opt/baza (or wherever docker-compose.prod.yml lives)
#   - docker compose stack already running (postgres/redis/backend/frontend/nginx all Up)

set -euo pipefail

COMPOSE="docker compose -f docker-compose.prod.yml"
EMAIL="${LETSENCRYPT_EMAIL:-owner@usebaza.ru}"
DOMAIN_PRIMARY="usebaza.ru"
DOMAIN_WWW="www.usebaza.ru"
CONF_HTTP="./infra/nginx/nginx.prod.conf"
CONF_SSL="./infra/nginx/nginx.prod.ssl.conf"
COMPOSE_NGINX_VOLUME_LINE="./infra/nginx/nginx.prod.conf:/etc/nginx/nginx.conf:ro"
COMPOSE_NGINX_VOLUME_LINE_SSL="./infra/nginx/nginx.prod.ssl.conf:/etc/nginx/nginx.conf:ro"

# Derive docker volume names (prefix = compose project = dir name, e.g. "baza")
PROJECT_NAME="$(basename "$(pwd)")"
VOL_CERTS="${PROJECT_NAME}_certbot_certs"
VOL_WWW="${PROJECT_NAME}_certbot_www"

echo "==> [1/4] Create .env symlink so compose stops WARNing"
if [[ ! -e .env ]]; then
    ln -sf .env.production .env
    echo "    created .env → .env.production"
else
    echo "    .env already exists, skipping"
fi

echo "==> [2/4] Obtain Let's Encrypt certificate for ${DOMAIN_PRIMARY}, ${DOMAIN_WWW}"
# Check if cert already exists
if docker run --rm -v "${VOL_CERTS}:/etc/letsencrypt" alpine \
        test -f "/etc/letsencrypt/live/${DOMAIN_PRIMARY}/fullchain.pem"; then
    echo "    cert already present, skipping certbot"
else
    echo "    running certbot --webroot…"
    docker run --rm \
        -v "${VOL_WWW}:/var/www/certbot" \
        -v "${VOL_CERTS}:/etc/letsencrypt" \
        certbot/certbot certonly --webroot \
            -w /var/www/certbot \
            -d "${DOMAIN_PRIMARY}" -d "${DOMAIN_WWW}" \
            --email "${EMAIL}" --agree-tos --no-eff-email -n
    echo "    certbot done"
fi

echo "==> [3/4] Swap nginx config to HTTPS version and reload"
# Update docker-compose.prod.yml to mount the SSL config
if grep -q "${COMPOSE_NGINX_VOLUME_LINE_SSL}" docker-compose.prod.yml; then
    echo "    compose already points at nginx.prod.ssl.conf"
else
    sed -i "s|${COMPOSE_NGINX_VOLUME_LINE}|${COMPOSE_NGINX_VOLUME_LINE_SSL}|" docker-compose.prod.yml
    echo "    swapped mount to nginx.prod.ssl.conf"
fi

# Recreate nginx container so it picks up the new mount
$COMPOSE up -d --no-deps --force-recreate nginx
sleep 3
echo "    nginx recreated"

echo "==> [4/4] Install weekly renewal cron"
CRON_CMD="/opt/baza/scripts/renew-ssl.sh"
cat > /usr/local/bin/baza-renew-ssl <<EOF
#!/usr/bin/env bash
set -e
cd /opt/baza
docker run --rm \\
    -v ${VOL_WWW}:/var/www/certbot \\
    -v ${VOL_CERTS}:/etc/letsencrypt \\
    certbot/certbot renew --webroot -w /var/www/certbot --quiet
docker compose -f docker-compose.prod.yml exec -T nginx nginx -s reload || true
EOF
chmod +x /usr/local/bin/baza-renew-ssl

CRON_LINE="17 4 * * 1 /usr/local/bin/baza-renew-ssl >> /var/log/baza-renew.log 2>&1"
if ! crontab -l 2>/dev/null | grep -qF "baza-renew-ssl"; then
    ( crontab -l 2>/dev/null || true; echo "${CRON_LINE}" ) | crontab -
    echo "    cron installed: Mondays 04:17 UTC"
else
    echo "    cron already present, skipping"
fi

echo ""
echo "========================================================"
echo "HTTPS setup complete. Verify:"
echo "  curl -sI https://${DOMAIN_PRIMARY}/ | head -3"
echo "  curl -s  https://${DOMAIN_PRIMARY}/api/health"
echo "========================================================"
