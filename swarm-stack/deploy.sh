#!/usr/bin/env bash
# Idempotent-ish deploy script: builds the image, ensures the swarm exists,
# creates the secret if missing, then deploys/updates the stack.
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
        echo "    ADVERTISE_ADDR=172.17.0.232 ./deploy.sh"
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
    echo "Secret 'jwt_secret' already exists (Swarm secrets are immutable - see rotate_secret.sh to change it)."
fi

echo "== Deploying stack '$STACK_NAME' =="
docker stack deploy -c docker-stack.yml "$STACK_NAME"

echo
echo "Deployed. Check status with:  docker stack services $STACK_NAME"
echo "App reachable via edge at:    http://localhost:80"
echo "Traefik dashboard (demo only): http://localhost:8081"
