# Axiler DevSecOps Take-Home — Secure Multi-Tenant Transaction Platform

একটা ছোট, synthetic multi-tenant transaction platform যেটা দিয়ে দেখানো হয়েছে:
tenant isolation (JWT দিয়ে), network trust boundary (Docker Swarm-এ edge vs
internal network), সরবরাহ-শৃঙ্খল (supply-chain) নিরাপত্তা (scan → SBOM → sign
→ push), deployment automation + auto-rollback, এবং per-tenant observability
(logs, metrics, dashboard, alert)।

## Repo গঠন

```
.
├── app-skeleton/       # ধাপ ২ — Flask app (health/search/transfer), JWT tenant isolation
├── swarm-stack/        # ধাপ ৩, ৪, ৭, ৮ — Docker Swarm stack, edge, rollback, observability config
├── .github/workflows/  # ধাপ ৫, ৬ — CI/CD pipeline (lint → scan → sbom → sign → push)
├── docs/               # diagram + design note (এই ফোল্ডার)
└── README.md           # এই ফাইল
```

প্রতিটা sub-folder-এর নিজস্ব বিস্তারিত README আছে (setup command, স্ক্রিপ্ট
ব্যাখ্যা সহ) — এটা শুধু পুরো প্রজেক্টের overview এবং scenario reproduction
guide হিসেবে কাজ করে।

## Quick Setup (স্থানীয়ভাবে চালানো)

```bash
# 1. Swarm mode চালু করা (একবারই দরকার)
docker swarm init

# 2. পুরো stack deploy
cd swarm-stack
chmod +x *.sh
./deploy.sh

# 3. Network boundary verify করা
./verify_network_boundary.sh

# 4. App-এর smoke test (edge/Traefik দিয়ে, port 80-এ)
export BASE_URL=http://localhost:80
export JWT_SECRET=devsecret123
bash ../app-skeleton/tests/smoke_test.sh
```

**Teardown:**
```bash
cd swarm-stack
./teardown.sh
```

## Trust Model (এক নজরে)

- **Tenant identity**: client একটা signed JWT পাঠায়; `tenant_id` claim
  শুধুমাত্র verified signature থেকে বের হয়, header/query param থেকে না।
  প্রতিটা data lookup tenant-scoped (`FAKE_DB[tenant_id]`)।
- **Network boundary**: `app` service শুধু internal `app-net`-এ, কোনো
  published port নেই — বাইরে থেকে সরাসরি reachable না। একমাত্র entry
  point Traefik (`edge-net` + `app-net` দুটোতেই)।
- **Secrets**: `jwt_secret`, `grafana_admin_password` — Docker Swarm
  secret হিসেবে mount করা, plaintext env var না।
- **Supply chain**: প্রতিটা image push হওয়ার আগে Trivy (vuln scan),
  Gitleaks (secret scan), Syft (SBOM) পাস করতে হয়; তারপর push হওয়া
  digest cosign দিয়ে keyless sign হয় (OIDC, কোনো private key স্টোর করা
  হয় না)।

বিস্তারিত rationale ও known gaps-এর জন্য দেখো [`docs/DESIGN_NOTE.md`](./DESIGN_NOTE.md)।

## Diagram

Build/release flow এবং runtime request flow — দেখো
[`docs/diagrams.md`](./diagrams.md)।

## তিনটা Scenario কীভাবে Reproduce করবে

### Scenario 1 — Vulnerable dependency থাকলে CI/CD block করে

```bash
# requirements.txt-এ ইচ্ছাকৃতভাবে একটা পুরনো/vulnerable version বসাও, push করো
git checkout -b demo/vuln-dep
# উদাহরণ: Flask==2.0.0 (পুরনো, known CVE সহ)
git commit -am "demo: intentionally vulnerable dependency"
git push origin demo/vuln-dep
```
GitHub Actions-এ গিয়ে দেখো **Trivy Vulnerability Scan** জব `HIGH`/`CRITICAL`
severity পেলে `--exit-code 1` দিয়ে fail করছে, এবং তার ফলে `push-and-sign`
জবই চলছে না (কারণ `needs: [vuln-scan, sbom]`)। ফলাফল: vulnerable image
কখনোই GHCR-এ push/sign হয় না।

### Scenario 2 — খারাপ deployment ধরা পড়ে, Swarm নিজে rollback করে

```bash
cd swarm-stack
./demo_bad_deploy.sh
```
এটা `FAIL_HEALTH=true` দিয়ে একটা bad update ট্রিগার করে। `docker-stack.yml`-এ
`update_config.failure_action: rollback` সেট করা আছে বলে Swarm নিজে
healthcheck fail ধরে আগের working version-এ ফিরে যায়। Verify:
```bash
docker service ps axiler_app --no-trunc   # "Rollback" স্টেট দেখাবে
curl http://localhost:80/health           # আবার 200 OK
```
(আগেই verify করা হয়েছে — task `s1ghyeivjuat7db9l2yp3grq5` unhealthy
detect হয়ে kill হয়, auto-rollback হয়, `/health` + smoke test দিয়ে
recovery confirm করা হয়েছে।)

### Scenario 3 — Unauthorized/suspicious traffic detect ও block হয়

```bash
# কোনো token ছাড়া (expect 401)
curl -o /dev/null -w "%{http_code}\n" http://localhost:80/search?account=ACC-1001

# ভুয়া/গার্বেজ token দিয়ে (expect 403)
curl -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer not-a-real-token" \
  http://localhost:80/search?account=ACC-1001
```
Application log-এ (`docker service logs axiler_app`) এই attempt-গুলোর
জন্য `auth_failed reason="missing_bearer_token"` বা
`auth_failed reason="invalid_signature"` লাইন দেখা যাবে — এটাই একটা
on-call engineer / SIEM-এর alert করার সিগন্যাল।

## Observability কোথায় দেখতে হবে

- **Grafana dashboard**: `http://localhost:3000` (Swarm-এ deploy করার পর)
  - `p95 Latency per Tenant`
  - `Per-tenant Error Rate`
  - `Request Rate per Tenant`
- **Alert rule**: Grafana → Alerting → Alert rules → `HighErrorRatePerTenant`
  (per-tenant error rate 10%-এর বেশি হলে ১ মিনিট পর Firing দেখাবে)
- **Prometheus**: internal-only (`app-net`), সরাসরি বাইরে থেকে reachable না;
  Grafana-র মাধ্যমে query হয়।
- **Raw metrics endpoint**: `app:8080/metrics` (শুধু internal network থেকে)

## Rollback (ম্যানুয়াল, দরকার হলে)

```bash
docker service rollback axiler_app
```

## AI Usage Disclosure

দেখো [`docs/AI_USAGE.md`](./AI_USAGE.md)।

## Known Gaps / প্রোডাকশনের জন্য প্রথম Improvement

সংক্ষিপ্ত তালিকা (বিস্তারিত rationale সহ design note-এ):
- Traefik-এ শুধু rate-limit আছে, JWT validation app-layer-এ — production-এ
  edge-এ WAF/JWT pre-check যোগ করা যেতে পারে (defense-in-depth)।
- Grafana সরাসরি port 3000 publish করছে, edge-এর মধ্য দিয়ে যাচ্ছে না —
  production-এ TLS + auth সহ Traefik-এর পেছনে রাখা উচিত।
- TLS/HTTPS বাদ দেওয়া হয়েছে সরলতার জন্য।
- Single-node Swarm; multi-node হলে overlay encryption ও placement
  constraints নিয়ে আলাদা কাজ লাগবে।
- Swarm secrets immutable — production-এ Vault বা external secret
  manager দিয়ে rotation আরও ভালোভাবে হ্যান্ডল করা উচিত।
