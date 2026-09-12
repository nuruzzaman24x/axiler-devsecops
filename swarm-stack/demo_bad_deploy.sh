#!/usr/bin/env bash
# Demonstrates Scenario 2 (Bad deployment -> detection -> rollback).
#
# It updates the running "app" service to a version whose /health endpoint
# always fails. Because the stack file sets:
#     update_config.failure_action: rollback
#     update_config.monitor: 15s
#     update_config.max_failure_ratio: 0
# Swarm will detect the failing healthcheck during the update and roll the
# service back to the previous (working) image/config automatically.
#
# If you prefer to demonstrate MANUAL rollback instead, comment out the
# "docker service update" watch loop below and just run:
#     docker service rollback axiler_app
set -e

echo "== Current service state =="
docker service ps axiler_app --no-trunc

echo
echo "== Triggering a bad update (FAIL_HEALTH=true) =="
docker service update \
    --env-add FAIL_HEALTH=true \
    --update-failure-action rollback \
    --update-monitor 15s \
    --update-max-failure-ratio 0 \
    axiler_app

echo
echo "== Watching rollout (Swarm should detect failure and roll back) =="
sleep 20
docker service ps axiler_app --no-trunc

echo
echo "If you see tasks with 'Rollback' in the CURRENT STATE column above,"
echo "Swarm auto-detected the bad health check and rolled back for you."
echo
echo "If it did NOT roll back automatically, force a manual rollback with:"
echo "    docker service rollback axiler_app"
