# Docker Swarm Stack — Network Boundary + Deployment

This is for **Step 3 (Docker Swarm stack + network boundary)** of the
assignment. It deploys the `app-skeleton` from Step 2, and demonstrates
the separation between the edge and internal networks.

## What's Here

| File | Purpose |
|---|---|
| `docker-stack.yml` | The full stack definition — services, networks, secrets, update/rollback policy |
| `deploy.sh` | Builds the image, creates the secret, deploys the stack — all in one command |
| `teardown.sh` | Removes the stack |
| `demo_bad_deploy.sh` | Scenario 2 demo — deploys a bad version to show auto-rollback |
| `verify_network_boundary.sh` | Proves the app service is not directly reachable from outside |

## Network Boundary — How It Works

```
                    external client
                          |
                          v
                  ┌───────────────┐
                  │   edge-net    │   <- only network with published ports (80, 8081)
                  │  (overlay)    │
                  └───────┬───────┘
                          │
                    ┌─────▼─────┐
                    │  traefik  │   <- on both networks, the sole entry point
                    └─────┬─────┘
                          │
                  ┌───────▼───────┐
                  │   app-net     │   <- no published ports, not reachable
                  │  (overlay)    │      from outside at all
                  └───────┬───────┘
                          │
                    ┌─────▼─────┐
                    │ app (x2)  │
                    └───────────┘
```

**Core idea:** the `app` service is on `app-net`, not on `edge-net`, and
has no published ports. So a client can never reach `app` directly — all
traffic is forced through Traefik. This is the actual implementation of
"keep backend services private, external clients use the controlled edge
path" — enforced in the config itself, not just drawn in a diagram.

## Rollback Strategy (basis for Scenario 2)

In `docker-stack.yml`:
```yaml
update_config:
  failure_action: rollback
  monitor: 15s
  max_failure_ratio: 0
```
Meaning: after a new version is deployed, Swarm monitors it for 15
seconds (including healthchecks). If any task fails
(`max_failure_ratio: 0` means zero tolerance for failure), **Swarm
automatically rolls back to the previous version** — no manual
intervention needed. For a manual rollback:
```bash
docker service rollback axiler_app
```

## Running Steps

```bash
cd swarm-stack
chmod +x *.sh
./deploy.sh
```

Then verify:
```bash
./verify_network_boundary.sh
```

Run the smoke test from the earlier step (through the edge, on port 80):
```bash
export BASE_URL=http://localhost:80
export JWT_SECRET=devsecret123
bash ../app-skeleton/tests/smoke_test.sh
```

Bad-deployment / rollback demo (Scenario 2):
```bash
./demo_bad_deploy.sh
```

To tear down:
```bash
./teardown.sh
```

## Notes on Secrets

- `JWT_SECRET` is no longer a plain environment variable — it's mounted
  as a Docker Swarm secret at `/run/secrets/jwt_secret`, and the app
  reads it from that file (`JWT_SECRET_FILE`).
- Swarm secrets are **immutable** — to change the value you have to
  create a new secret under a new name (e.g. `jwt_secret_v2`) and update
  the service. In production this should be handled better with Vault or
  an external secret manager — noted as a "known shortcut" in the design
  note.

## Known Shortcuts (for local demo, not production)

- The Traefik dashboard port (8081) is left open for convenience — in
  production this should be disabled or placed on a separate secured
  network.
- A single-node Swarm is assumed; a multi-node setup would need separate
  consideration for placement constraints, overlay network encryption
  (`--opt encrypted`), and manager quorum.
- TLS/HTTPS is omitted for simplicity — in production, Traefik should
  enforce TLS via Let's Encrypt or an internal CA.

## Next Steps

- Step 4: add rate-limiting and edge-level auth/policy control to Traefik
- Step 5: a CI/CD pipeline that builds, scans, signs, and pushes this
  image to a registry
