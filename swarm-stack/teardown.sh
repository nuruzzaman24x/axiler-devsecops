#!/usr/bin/env bash
set -e
STACK_NAME="axiler"

echo "== Removing stack '$STACK_NAME' =="
docker stack rm "$STACK_NAME"

echo "Waiting for networks/containers to clean up..."
sleep 5

echo "Done. (Secrets are left in place intentionally - remove manually with"
echo "  docker secret rm jwt_secret"
echo "if you want a fully clean slate.)"
