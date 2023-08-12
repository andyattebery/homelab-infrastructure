#!/usr/bin/env sh

# usage: certbot_create_cert.sh <docker-compose-path> <email> <dns-cloudflare-credentials-path-in-container> <domain>
docker compose -f $1 run --rm --entrypoint="" certbot certbot certonly \
      --config-dir /certbot/config \
      --work-dir /certbot/work \
      --logs-dir /certbot/logs \
      --keep-until-expiring \
      --email $2 \
      --non-interactive \
      --agree-tos \
      --dns-cloudflare \
      --dns-cloudflare-credentials $3 \
      --domain $4