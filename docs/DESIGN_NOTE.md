# Design Note — Secure Multi-Tenant Transaction Platform

## 1. Architecture Decisions and Rationale

**Tenant identity: JWT, not a raw header.**
A raw `X-Tenant-ID` header would let any client simply set that header and
claim to be a different tenant — that's not a trust boundary, just an
unverified assertion. Instead, tenant identity lives in a **signed JWT**
carrying a `tenant_id` claim, and the app only trusts that claim after
verifying the signature (`jwt.decode(token, JWT_SECRET, ...)`). In
production, this token would be issued by an SSE edge / identity provider
after verifying the client's real authentication (mTLS or OAuth
client-credentials) — in this repo, `tests/generate_token.py` mints
tokens itself purely for testing, which is a **known shortcut**.

**Network layering: two layers (edge-net, app-net), not three.**
Two layers felt sufficient because there's really only one boundary that
matters: internet-facing traffic vs. internal service-to-service traffic.
Traefik is the sole bridge — every other backend service (app,
Prometheus) sits on `app-net` only, with no published ports. This is
enforced in the actual Swarm config, not just drawn in a diagram
(`verify_network_boundary.sh` proves the app's port 8080 is not directly
reachable from the host).

**Tool choices:** Traefik (native Docker Swarm provider support,
label-based config, built-in rate-limit middleware), GitHub Actions
(already integrated with the repo), Trivy/Gitleaks/Syft/cosign
(industry-standard, good Action/CLI support, keyless signing avoids
private-key management), Prometheus + Grafana (de facto standard,
label-based per-tenant metric slicing is easy).

## 2. Supply-Chain Approach

Every pushed image must pass these gates:
`lint/test → secret-scan (Gitleaks) → build → vuln-scan (Trivy, exit-code
1 on HIGH/CRITICAL) → SBOM (Syft, CycloneDX) → push to GHCR by digest →
cosign sign (keyless, OIDC) → cosign attest (SBOM attached)`.

**Key design decisions:**
- Images are pushed by **digest**, not by mutable tag — the deploy script
  references the digest, preventing a "same tag, different content"
  attack.
- Cosign signing is **keyless** (OIDC-based) — no private signing key is
  ever stored in the repo or in secrets, so there's no key to leak.
- The vulnerability gate is a hard block: a HIGH/CRITICAL finding fails
  the pipeline and the push/sign job never runs
  (`needs: [vuln-scan, sbom]`).
- Trivy is run directly as a Docker container (`aquasec/trivy`) rather
  than through the official GitHub Action, because that Action's
  binary-download installer had a known flaky upstream issue; Docker Hub
  pulls were already proven reachable earlier in the same pipeline, so
  this path is more reliable.

## 3. Secrets / Identity Model

- **JWT secret**: mounted as a Docker Swarm secret (`jwt_secret`) at
  `/run/secrets/jwt_secret`; the app reads it via `JWT_SECRET_FILE`. A
  plaintext env var (`JWT_SECRET`) is only a local-dev fallback.
- **A real bug was found and fixed here**: in an earlier version,
  `docker-stack.yml` correctly set `JWT_SECRET_FILE`, but `app/main.py`
  never actually read it — it only used the `JWT_SECRET` env var (and
  fell back to a hardcoded `"devsecret123"` if that was missing). So even
  with the Swarm secret properly mounted, the app was silently falling
  back to a hardcoded, insecure default. This was caught through manual
  review and fixed by writing `_load_jwt_secret()` (priority:
  `JWT_SECRET_FILE` > `JWT_SECRET` > **fail loudly at startup**, instead
  of a silent insecure default). (This is also the concrete example used
  in the AI usage disclosure — see `docs/AI_USAGE.md`.)
- **Grafana admin password**: similarly mounted as a Swarm secret
  (`grafana_admin_password`).
- **CI/CD secrets**: the built-in `GITHUB_TOKEN` (repo-scoped,
  auto-rotated) is used for GHCR push, so no long-lived PAT or hardcoded
  credential lives in the repo. Cosign signing uses OIDC
  (`id-token: write` permission) — no signing key is stored as a secret
  anywhere.
- **Least privilege**: the workflow's `permissions:` block grants only
  the scopes actually needed (`contents: read`, `packages: write`,
  `id-token: write`).

## 4. Observability

- **Structured logs**: every log line carries `tenant_id`, `request_id`,
  and (on health/version endpoints) `version` — JSON-ish format, easy to
  grep/filter or ingest into Loki later.
- **Metrics**: two Prometheus metrics, both labeled by `tenant_id` —
  `http_request_duration_seconds` (Histogram, for latency percentiles)
  and `http_requests_total` (Counter, for error rate, labeled by
  `http_status`). Requests that fail auth get `tenant_id="unauthenticated"`
  — itself a signal for Scenario 3.
- **Dashboards**: three separate Grafana dashboards — p95 Latency per
  Tenant, Per-tenant Error Rate, Request Rate per Tenant — so an operator
  can see at a glance which tenant is affected.
- **Alert**: `HighErrorRatePerTenant` fires when a tenant's 5xx/total
  ratio (using an `or ... * 0` fallback so tenants with zero errors still
  report a value instead of "no data") exceeds 10% for 1 minute (pending
  period).

## 5. Rollback Strategy

`docker-stack.yml` sets `update_config: failure_action: rollback,
monitor: 15s, max_failure_ratio: 0` — after a new deployment, Swarm
monitors healthchecks for 15 seconds; if even one task fails, it
**automatically** rolls back, with no human intervention. Verified via
`demo_bad_deploy.sh` — deploying a `FAIL_HEALTH=true` version, Swarm
detected it and auto-rolled back, confirmed by `/health` + the smoke
test. Manual override: `docker service rollback axiler_app`.

## 6. Restricted-Connectivity Delivery Design

GHCR is used as the registry, but since this is a single-node local demo,
the `app` service is pinned to the manager node
(`node.role == manager`) rather than distributed via a registry. A local
registry (`registry:2`, port 5000) is also running — in a restricted or
air-gapped environment with no external network access, images could be
pushed/pulled from this local registry instead, allowing deployment
without any dependency on GHCR. In a real multi-node production
deployment, each node would need registry credentials / an
imagePullSecret to pull from GHCR, and the placement constraint would be
removed.

## 7. Known Gaps and First Improvements Before Production

1. **No edge-level JWT validation** — Traefik only rate-limits (5 req/s
   average, burst 10); JWT validation is entirely at the app layer. This
   is deliberate (keeping auth logic centralized, avoiding duplicated
   validation logic), but from a defense-in-depth perspective, adding a
   lightweight edge pre-check (e.g. a ForwardAuth middleware) in
   production would be a good first improvement — invalid tokens could
   be rejected before ever reaching the app, saving resources.
2. **Grafana publishes a port directly** (on `edge-net`, port 3000) with
   no TLS or auth hardening beyond Grafana's own login. In production this
   should sit behind Traefik with TLS and access control.
3. **TLS/HTTPS omitted** — the whole demo runs over plain HTTP for
   simplicity. Production should enforce TLS via Traefik with Let's
   Encrypt or an internal CA.
4. **Single-node Swarm** — a multi-node setup would need overlay network
   encryption (`--opt encrypted`) and manager quorum considerations.
5. **Swarm secrets are immutable** — rotating a secret requires creating
   one under a new name and updating the service. Production should
   handle this more gracefully with HashiCorp Vault or a cloud secret
   manager.
6. **Traefik dashboard (port 8081) is exposed in insecure mode** — only
   for local demo debugging; in production this should be disabled or
   placed on a separate secured network.

**If only one thing could be fixed first before going to production:**
enabling TLS and moving Grafana behind the edge — these are the two most
directly externally-visible gaps right now; the rest are internal
architecture considerations, not zero-day exposure.
