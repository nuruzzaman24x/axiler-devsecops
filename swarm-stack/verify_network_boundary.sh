#!/usr/bin/env bash
# Verifies the network boundary claim: the "app" service should NOT be
# reachable directly from the host, only through the edge (Traefik).
set -e

echo "== Services and their published ports =="
docker service ls

echo
echo "== Attempting to hit the app service directly on its container port (8080) =="
echo "This should FAIL (connection refused / no route) because app has no published port:"
if curl -s -m 3 http://localhost:8080/health > /dev/null 2>&1; then
    echo "UNEXPECTED: app port 8080 is reachable directly from the host!"
    exit 1
else
    echo "OK: app is not directly reachable on :8080 from the host, as expected."
fi

echo
echo "== Confirming the app IS reachable through the edge (port 80) =="
curl -s http://localhost:80/health | python3 -m json.tool
