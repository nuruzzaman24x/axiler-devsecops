# Axiler DevSecOps Take-Home — Secure Multi-Tenant Transaction Platform

A small, synthetic multi-tenant transaction platform demonstrating: tenant
isolation (via JWT), a network trust boundary (edge vs. internal network on
Docker Swarm), supply-chain security (scan → SBOM → sign → push), deployment
automation with auto-rollback, and per-tenant observability (logs, metrics,
dashboards, alerting).

## Repository Layout

```
.
├── app-skeleton/       # Step 2 — Flask app (health/search/transfer), JWT tenant isolation
├── swarm-stack/        # Steps 3, 4, 7, 8 — Docker Swarm stack, edge, rollback, observability config
├── .github/workflows/  # Steps 5, 6 — CI/CD pipeline (lint → scan → sbom → sign → push)
├── docs/               # Diagrams and design note (this folder)
└── README.md           # This file
```

Each sub-folder has its own detailed README (setup commands, script
explanations). This file is a project overview and a scenario-reproduction
guide.

## Quick Setup (Local)

```bash
# 1. Enable Swarm mode (one-time)
docker swarm init

# 2. Deploy the full stack
cd swarm-stack
chmod +x *.sh
./deploy.sh

# 3. Verify the network boundary
./verify_network_boundary.sh

# 4. Smoke test the app (through the edge/Traefik, on port 80)
export BASE_URL=http://localhost:80
export JWT_SECRET=devsecret123
bash ../app-skeleton/tests/smoke_test.sh
```

**Teardown:**
```bash
cd swarm-stack
./teardown.sh
```

## Trust Model (at a glance)

- **Tenant identity**: the client sends a signed JWT; the `tenant_id` claim
  is only trusted after signature verification, never taken from a header
  or query parameter. Every data lookup is tenant-scoped
  (`FAKE_DB[tenant_id]`).
- **Network boundary**: the `app` service lives only on the internal
  `app-net`, with no published ports — it is not directly reachable from
  outside. The only entry point is Traefik (attached to both `edge-net`
  and `app-net`).
- **Secrets**: `jwt_secret` and `grafana_admin_password` are mounted as
  Docker Swarm secrets, not passed as plaintext environment variables.
- **Supply chain**: every image must pass Trivy (vulnerability scan),
  Gitleaks (secret scan), and Syft (SBOM) before it is pushed; the pushed
  digest is then signed keylessly with cosign (via OIDC, no private key
  stored anywhere).

For detailed rationale and known gaps, see
[`docs/DESIGN_NOTE.md`](./docs/DESIGN_NOTE.md).

## Diagrams

Build/release flow and runtime request flow — see
[`docs/diagrams.md`](./docs/diagrams.md).

## Reproducing the Three Required Scenarios

### Scenario 1 — CI/CD blocks a release with a vulnerable dependency

```bash
git checkout -b demo/vuln-dep
# Example: intentionally add an old/vulnerable version, e.g. Flask==2.0.0
git commit -am "demo: intentionally vulnerable dependency"
git push origin demo/vuln-dep
```
In GitHub Actions, the **Trivy Vulnerability Scan** job fails
(`--exit-code 1`) on HIGH/CRITICAL findings, and the `push-and-sign` job
never runs (`needs: [vuln-scan, sbom]`). Result: a vulnerable image is
never pushed or signed to GHCR.

(Already verified once for real: the pipeline's Trivy scan caught two
genuine HIGH-severity CVEs in the originally-pinned `PyJWT==2.9.0`
dependency — CVE-2026-32597 and CVE-2026-48526 — and correctly failed the
pipeline before any push/sign step ran. Fixed by bumping to
`PyJWT==2.13.0`.)

### Scenario 2 — A bad deployment is detected and Swarm rolls it back

```bash
cd swarm-stack
./demo_bad_deploy.sh
```
This triggers a bad update with `FAIL_HEALTH=true`. Because
`docker-stack.yml` sets `update_config.failure_action: rollback`, Swarm
detects the failing healthcheck and automatically reverts to the previous
working version. Verify:
```bash
docker service ps axiler_app --no-trunc   # shows a "Rollback"/"Failed" state on the bad task
curl http://localhost:80/health           # back to 200 OK
```
(Already verified: the bad task was detected as unhealthy after
repeated `/health` 500s, was killed by Swarm, and the existing healthy
replica kept serving `200 OK` throughout — zero downtime. Recovery was
confirmed via `curl /health` and the smoke test.)

### Scenario 3 — Unauthorized/suspicious traffic is detected and blocked

```bash
# No token at all (expect 401)
curl -o /dev/null -w "%{http_code}\n" http://localhost:80/search?account=ACC-1001

# Garbage/invalid token (expect 403)
curl -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer not-a-real-token" \
  http://localhost:80/search?account=ACC-1001
```
The application log (`docker service logs axiler_app`) shows
`auth_failed reason="missing_bearer_token"` or
`auth_failed reason="invalid_signature"` entries for these attempts — the
exact signal an on-call engineer or a SIEM would alert on. A sustained
burst of these (see `SuspiciousUnauthenticatedTraffic` below) also fires
a Prometheus alert.

## Where to Look for Observability

- **Grafana dashboards**: `http://localhost:3000` (once the stack is
  deployed) — three dashboards, source-controlled under
  `swarm-stack/grafana/dashboards/`:
  - `p95 Latency per Tenant`
  - `Per-tenant Error Rate`
  - `Request Rate per Tenant`
- **Alert rules**: defined declaratively in
  `swarm-stack/alert_rules.yml` (loaded by Prometheus, **not** created
  by hand in the Grafana UI). View firing/pending state at
  `http://localhost:9090/alerts`:
  - `HighErrorRate` — fires when overall 5xx/total ratio exceeds 5% for
    1 minute (Scenario 2 signal).
  - `SuspiciousUnauthenticatedTraffic` — fires when unauthenticated
    request rate exceeds 3 req/s for 30s (Scenario 3 signal). **Verified
    firing** with a sustained burst of token-less requests.
  - `EdgeRateLimitingActive` — fires when Traefik's rate-limit
    middleware has been returning HTTP 429 for at least 30s, confirming
    the edge control in Step 4 is actually doing something. **Verified
    firing** with `demo_ratelimit.sh`.
- **Prometheus**: internal-only (`app-net`), not reachable from outside
  the swarm; queried by Grafana internally. Rules can be inspected at
  `http://localhost:9090/rules`.
- **Raw metrics endpoint**: `app:8080/metrics` (internal network only).

## Rollback (manual, if needed)

```bash
docker service rollback axiler_app
```

## AI Usage Disclosure

See [`docs/AI_USAGE.md`](./docs/AI_USAGE.md).

## Known Gaps / First Improvements Before Production

Summary (full rationale in the design note):
- Traefik only rate-limits; JWT validation happens at the app layer. In
  production, an edge-level pre-check (e.g. a WAF or a ForwardAuth
  middleware) could add defense-in-depth.
- Grafana publishes port 3000 directly instead of going through the edge —
  in production it should sit behind Traefik with TLS and access control.
- TLS/HTTPS was omitted for simplicity.
- Single-node Swarm; a multi-node setup would need overlay network
  encryption and placement constraints revisited.
- Swarm secrets are immutable — production should use Vault or an
  external secret manager for proper rotation.
