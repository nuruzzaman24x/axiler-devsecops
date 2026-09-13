# Application Skeleton — Search / Transfer / Health

This is the ready-to-use starter for **Step 2 (Application skeleton)** of
the assignment. It's not the whole assignment — just the app layer. The
rest (Swarm, CI/CD, edge, observability) builds on top of this skeleton
in later steps.

## What's Here

- `app/main.py` — the Flask service: `/health`, `/search`, `/transfer`
- `tests/generate_token.py` — script to mint a test tenant JWT
- `tests/smoke_test.sh` — manually verifies every endpoint and the
  isolation logic
- `Dockerfile` — non-root user, healthcheck included
- `requirements.txt`

## Tenant Trust Model (important — be ready to explain this in interview)

1. The client sends a signed JWT in the `Authorization: Bearer <token>`
   header.
2. The token contains a `tenant_id` claim.
3. The app only trusts the `tenant_id` extracted from a **verified
   signature** — never reads it directly from a header or query
   parameter.
4. Every data lookup (`FAKE_DB[tenant_id]`) is tenant-scoped, so there's
   no code path that can accidentally see another tenant's data.
5. For a transfer, **both** `from_account` and `to_account` must belong
   to the calling tenant — otherwise 403.

**Difference from production:** in this script we mint the token
ourselves for testing. In reality this token would be issued by an SSE
edge / identity provider after verifying the client's real authentication
(mTLS, OAuth client-credentials, etc.). This gap should be listed as a
"known shortcut" in the design note.

## JWT Secret Configuration (Step 6 — Secrets and Least Privilege)

`JWT_SECRET` can now be provided in two ways, following a priority order:

1. **`JWT_SECRET_FILE`** — path to a mounted secret file (for
   production/Swarm). Mounted as a Docker Swarm secret at
   `/run/secrets/jwt_secret`; the app reads directly from that file. If
   set, this always takes priority.
2. **`JWT_SECRET`** — plain environment variable, for local dev only.
3. If neither is set, the app **fails at startup** (`RuntimeError`) —
   it does not silently fall back to an insecure hardcoded default.

**Bug-fix note:** in an earlier version, even though `docker-stack.yml`
set `JWT_SECRET_FILE`, `app/main.py` never actually read it — the code
only used the `JWT_SECRET` env var (falling back to a hardcoded
`"devsecret123"` if not set). So even with the Swarm secret mounted, the
app was silently falling back to the hardcoded default and the secret was
never actually used. This was caught through manual review and fixed with
the `_load_jwt_secret()` function — `JWT_SECRET_FILE` now takes priority,
and if no secret is available, the app shuts down immediately instead of
running silently.

## Running Locally

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export JWT_SECRET=devsecret123
python app/main.py
```

In another terminal:

```bash
export JWT_SECRET=devsecret123
bash tests/smoke_test.sh
```

## Running with Docker

```bash
docker build -t txn-platform:dev .
docker run -p 8080:8080 -e JWT_SECRET=devsecret123 txn-platform:dev
```

To simulate a production/Swarm-style file-based secret:

```bash
echo -n "devsecret123" > /tmp/fake_secret
docker run -p 8080:8080 \
  -v /tmp/fake_secret:/run/secrets/jwt_secret:ro \
  -e JWT_SECRET_FILE=/run/secrets/jwt_secret \
  txn-platform:dev
```

## Bad-Deployment Demo (ready for Scenario 2)

```bash
docker run -p 8080:8080 -e JWT_SECRET=devsecret123 -e FAIL_HEALTH=true txn-platform:dev
curl http://localhost:8080/health   # returns 500
```

This flag is later used in the Swarm stack file as a "bad version" to
demonstrate rollback.

## What's Added Next (on top of this skeleton)

- Docker Swarm stack file (with network boundary)
- Traefik/Nginx edge (rate limiting, JWT validation forwarding)
- GitHub Actions CI/CD (scan, SBOM, sign, gate)
- Prometheus/Grafana observability

---

Note (useful for the README/scenario-reproduction section in Step 9, and
the disclosure in Step 10):

"Scenario 2 was verified with `demo_bad_deploy.sh` — the bad task
`s1ghyeivjuat7db9l2yp3grq5` was detected as unhealthy and killed, Swarm
auto-rolled back, and recovery was confirmed via `curl /health` and the
smoke test."
