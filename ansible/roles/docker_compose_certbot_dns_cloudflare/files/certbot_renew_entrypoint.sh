#!/usr/bin/env sh

trap exit TERM
while :; do
  certbot renew \
    --config-dir /certbot/config \
    --work-dir /certbot/work \
    --logs-dir /certbot/logs
  sleep 24h & wait ${!}
done