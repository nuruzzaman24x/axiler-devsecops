#!/usr/bin/env bash
# Idempotent-ish deploy script: builds the image, ensures the swarm exists,
# creates required secrets if missing, then deploys/updates the stack.
set -e

STACK_NAME="axiler"
IMAGE_TAG="txn-platform:dev"

echo "== Ensuring Swarm mode is active =="
if ! docker info --format '{{.Swarm.LocalNodeState}}' | grep -q active; then
    if [ -n "$ADVERTISE_ADDR" ]; then
        echo "Initializing swarm with explicit advertise address: $ADVERTISE_ADDR"
        docker swarm init --advertise-addr "$ADVERTISE_ADDR"
    else
        echo "WARNING: ADVERTISE_ADDR not set. Docker will auto-pick an interface,"
        echo "which is unreliable on multi-homed hosts. Recommended:"
        echo "    ADVERTISE_ADDR=<your-node-ip> ./deploy.sh"
        docker swarm init
    fi
fi

echo "== Building application image =="
docker build -t "$IMAGE_TAG" ../app-skeleton

echo "== Ensuring jwt_secret exists =="
if ! docker secret ls --format '{{.Name}}' | grep -qx jwt_secret; then
    printf "devsecret123" | docker secret create jwt_secret -
    echo "Created secret 'jwt_secret'."
else
    echo "Secret 'jwt_secret' already exists (Swarm secrets are immutable - to rotate it, create a new secret with a new name and update the stack file / service to reference it)."
fi

echo "== Ensuring grafana_admin_password exists =="
if ! docker secret ls --format '{{.Name}}' | grep -qx grafana_admin_password; then
    printf "changeme123" | docker secret create grafana_admin_password -
    echo "Created secret 'grafana_admin_password' (login: admin / changeme123 - LOCAL DEMO ONLY)."
else
    echo "Secret 'grafana_admin_password' already exists."
fi

echo "== Deploying stack '$STACK_NAME' =="
docker stack deploy -c docker-stack.yml "$STACK_NAME"

echo
echo "Deployed. Check status with:  docker stack services $STACK_NAME"
echo "App reachable via edge at:     http://localhost:80"
echo "Traefik dashboard (demo only): http://localhost:8081"
echo "Prometheus:                    http://localhost:9090"
echo "Grafana (admin/changeme123):   http://localhost:3000"
