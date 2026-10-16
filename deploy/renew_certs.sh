#!/usr/bin/env bash
# Renew the Let's Encrypt certificate and reload nginx. Installed on the cloud
# VM as a systemd timer (isosafe-certbot-renew.timer) by deploy/first_deploy.sh,
# but safe to run by hand as root:
#
#   sudo DOMAIN=demo.isosafe.com APP_DIR=/opt/isosafe/app deploy/renew_certs.sh
#
# Runs from $APP_DIR so docker compose picks up that directory's .env.
set -euo pipefail

DOMAIN="${DOMAIN:?set DOMAIN, e.g. demo.isosafe.com}"
APP_DIR="${APP_DIR:-/opt/isosafe/app}"
COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.cloud.yml -f docker-compose.aws.yml)

cd "$APP_DIR"
mkdir -p deploy/certs deploy/acme

docker run --rm \
  -v "$APP_DIR/deploy/certs:/etc/letsencrypt" \
  -v "$APP_DIR/deploy/acme:/var/www/acme" \
  certbot/certbot renew --webroot -w /var/www/acme --quiet

if [[ -f "deploy/certs/live/$DOMAIN/fullchain.pem" ]]; then
  install -m 644 "deploy/certs/live/$DOMAIN/fullchain.pem" deploy/certs/server.crt
  install -m 600 "deploy/certs/live/$DOMAIN/privkey.pem" deploy/certs/server.key
  docker compose "${COMPOSE_FILES[@]}" exec -T nginx nginx -s reload
  echo "certificate renewed and nginx reloaded for $DOMAIN"
else
  echo "no certificate at deploy/certs/live/$DOMAIN; run first_deploy.sh first" >&2
  exit 1
fi