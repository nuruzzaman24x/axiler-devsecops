# Design Note — Secure Multi-Tenant Transaction Platform

## ১. Architecture সিদ্ধান্ত ও কারণ

**Tenant identity: JWT, raw header না।**
একটা raw `X-Tenant-ID` header ব্যবহার করলে যে কোনো client নিজেই সেই header
বসিয়ে অন্য tenant-এর পরিচয় claim করতে পারতো — এটা কোনো trust boundary না,
শুধু একটা unverified assertion। এর বদলে tenant identity একটা **signed JWT**-এ
রাখা হয়েছে, যেখানে `tenant_id` claim থাকে এবং app শুধু signature verify করার
পরেই সেই claim বিশ্বাস করে (`jwt.decode(token, JWT_SECRET, ...)`)। Production-এ
এই token issue করবে একটা SSE edge / identity provider, client-এর real
authentication (mTLS বা OAuth client-credentials) verify করার পরে — এই repo-তে
`tests/generate_token.py` শুধু demo/টেস্টের জন্য নিজেরাই token বানায়, এটা একটা
**known shortcut**।

**Network layering: দুইটা layer (edge-net, app-net), তিনটা না।**
দুইটা layer যথেষ্ট মনে হয়েছে কারণ trust boundary আসলে একটাই জায়গায় দরকার:
internet-facing traffic বনাম internal service-to-service traffic। Traefik
একমাত্র সেতু — দুই network-এই আছে, বাকি সব backend service (app, Prometheus)
শুধু `app-net`-এ, কোনো published port ছাড়া। এটা diagram-এই না, actual Swarm
config-এই enforce করা (`verify_network_boundary.sh` দিয়ে প্রমাণিত: app port
8080 সরাসরি host থেকে reachable না)।

**Tool নির্বাচন:** Traefik (native Docker Swarm provider support, label-based
config, built-in rate-limit middleware), GitHub Actions (repo-র সাথে already
integrated), Trivy/Gitleaks/Syft/cosign (industry-standard, ভালো Action/CLI
সাপোর্ট, keyless signing দিয়ে private key management এড়ানো যায়), Prometheus +
Grafana (de facto standard, label-based per-tenant metric slicing সহজ)।

## ২. Supply-chain Approach

প্রতিটা push হওয়া image এই gate-গুলো পার হতে হয়:
`lint/test → secret-scan (Gitleaks) → build → vuln-scan (Trivy, HIGH/CRITICAL
এ exit-code 1) → SBOM (Syft, CycloneDX) → push to GHCR by digest → cosign sign
(keyless, OIDC) → cosign attest (SBOM attached)`।

**গুরুত্বপূর্ণ ডিজাইন সিদ্ধান্ত:**
- Image push হয় শুধু **digest** দিয়ে, mutable tag দিয়ে না — deploy script
  digest reference করবে, যাতে "same tag, different content" আক্রমণ সম্ভব না হয়।
- Cosign **keyless** (OIDC-ভিত্তিক) — কোনো private signing key repo বা secret-এ
  স্টোর করতে হয় না, ফলে key-leak-এর risk-ই নেই।
- Vulnerability gate hard block: HIGH/CRITICAL পেলে pipeline fail করে, image
  push/sign জবই চলে না (`needs: [vuln-scan, sbom]`)।
- Trivy CLI সরাসরি Docker image হিসেবে চালানো হয়েছে (`aquasec/trivy` container),
  official GitHub Action না ব্যবহার করে — কারণ সেই Action-এর binary-download
  installer একটা পরিচিত flaky upstream issue-এর শিকার হচ্ছিল; Docker Hub pull
  এই pipeline-এই আগে প্রমাণিত reachable, তাই এটা বেশি নির্ভরযোগ্য পথ।

## ৩. Secrets / Identity Model

- **JWT secret**: Docker Swarm secret (`jwt_secret`) হিসেবে
  `/run/secrets/jwt_secret`-এ mount, app `JWT_SECRET_FILE` থেকে পড়ে। Plaintext
  env var (`JWT_SECRET`) শুধু local dev fallback।
- **প্রকৃত bug ধরা পড়েছিল এবং ঠিক করা হয়েছে**: প্রথম ভার্সনে
  `docker-stack.yml`-এ `JWT_SECRET_FILE` সেট থাকলেও `app/main.py` আসলে সেটা
  পড়ত না — শুধু `JWT_SECRET` env var (আর না থাকলে hardcoded
  `"devsecret123"`) ব্যবহার করত। ফলে Swarm secret mount হলেও app silently
  hardcoded default-এ fallback করছিল। এটা manually verify করে ধরা হয় এবং
  `_load_jwt_secret()` ফাংশন লিখে ঠিক করা হয়েছে (priority:
  `JWT_SECRET_FILE` > `JWT_SECRET` > **fail loudly at startup**, silent
  insecure default না)। (এই ঘটনাটাই AI usage disclosure-এর জন্য concrete
  উদাহরণ, দেখো `docs/AI_USAGE.md`।)
- **Grafana admin password**: একইভাবে Swarm secret
  (`grafana_admin_password`) হিসেবে mount।
- **CI/CD secrets**: GitHub Actions built-in `GITHUB_TOKEN` ব্যবহার করা
  হয়েছে GHCR push-এর জন্য (repo-scoped, auto-rotated), আলাদা করে কোনো
  long-lived PAT বা hardcoded credential repo-তে নেই। Cosign signing OIDC
  (`id-token: write` permission) দিয়ে, কোনো key secret হিসেবে স্টোর করা
  হয়নি।
- **Least privilege**: workflow-এর `permissions:` ব্লকে শুধু প্রয়োজনীয়
  scope দেওয়া (`contents: read`, `packages: write`, `id-token: write`)।

## ৪. Observability

- **Structured logs**: প্রতিটা log line-এ `tenant_id`, `request_id`,
  এবং (health/version endpoint-এ) `version` — JSON-ish format, তাই সহজে
  grep/filter করা যায় বা পরে Loki-তে ingest করা যায়।
- **Metrics**: দুইটা Prometheus metric, দুটোই `tenant_id` label সহ —
  `http_request_duration_seconds` (Histogram, latency percentile হিসাবের
  জন্য) এবং `http_requests_total` (Counter, error rate হিসাবের জন্য,
  `http_status` label সহ)। Auth-fail হওয়া request-গুলো
  `tenant_id="unauthenticated"` লেবেল পায় — এটা নিজেই Scenario 3-এর জন্য
  একটা signal।
- **Dashboard**: তিনটা panel — p95 Latency per Tenant, Per-tenant Error
  Rate, Request Rate per Tenant — একজন অপারেটর এক নজরে বুঝতে পারে কোন
  tenant-এ সমস্যা হচ্ছে।
- **Alert**: `HighErrorRatePerTenant` rule, per-tenant 5xx/total ratio
  (`or ... * 0` fallback দিয়ে zero-error tenant-এর জন্যও ডেটা নিশ্চিত করা
  হয়েছে, "no data" এড়াতে) 10%-এর বেশি হলে ১ মিনিট (pending period) পর
  Firing হয়।

## ৫. Rollback Strategy

`docker-stack.yml`-এ `update_config: failure_action: rollback,
monitor: 15s, max_failure_ratio: 0` — নতুন deployment-এর পর ১৫ সেকেন্ড
Swarm নিজে healthcheck monitor করে; একটাও task fail করলে **automatic**
rollback হয়, কোনো human intervention ছাড়াই। `demo_bad_deploy.sh` দিয়ে এটা
verify করা হয়েছে — `FAIL_HEALTH=true` version deploy করে, Swarm detect
করে auto-rollback করে, `/health` + smoke test দিয়ে recovery confirm করা
হয়েছে। Manual override: `docker service rollback axiler_app`।

## ৬. Restricted-connectivity Delivery Design

Registry হিসেবে GHCR ব্যবহার করা হয়েছে, কিন্তু local demo/single-node
Swarm-এ multi-node distribution দরকার নেই বলে placement constraint
(`node.role == manager`) দিয়ে single node-এ pin করা আছে। একটা local
registry (`registry:2`, port 5000) ও চালু রাখা হয়েছে — কোনো external
network access না থাকা restricted পরিবেশে (air-gapped বা limited
connectivity), image local registry-তে push/pull করে চালানো যায়, যেটা
GHCR-এর মতো external dependency ছাড়াই deploy সম্ভব করে। Production
multi-node হলে GHCR-থেকে pull করার জন্য প্রতিটা node-এ registry
credential/imagePullSecret দরকার হবে, আর placement constraint সরিয়ে ফেলতে
হবে।

## ৭. Known Gaps ও প্রোডাকশনের জন্য প্রথম Improvement

1. **Edge-level JWT validation নেই** — Traefik শুধু rate-limit করে
   (5 req/s avg, burst 10); JWT validation পুরোপুরি app-layer-এ। এটা একটা
   ইচ্ছাকৃত সিদ্ধান্ত (auth logic এক জায়গায় কেন্দ্রীভূত রাখা, duplicate
   validation logic এড়ানো), কিন্তু defense-in-depth-এর দিক থেকে
   production-এ edge-এও একটা lightweight pre-check (যেমন ForwardAuth
   middleware) যোগ করা প্রথম উন্নতি হতে পারে — invalid token request app
   পর্যন্ত পৌঁছানোর আগেই বাদ দেওয়া যাবে, resource সাশ্রয় হবে।
2. **Grafana সরাসরি port publish করছে** (`edge-net`-এ, port 3000) —
   TLS বা auth hardening ছাড়া। Production-এ এটা Traefik-এর পেছনে নিয়ে
   গিয়ে TLS + access control যোগ করা উচিত।
3. **TLS/HTTPS বাদ দেওয়া** — সরলতার জন্য পুরো demo HTTP-তে। Production-এ
   Traefik-এ Let's Encrypt বা internal CA দিয়ে TLS বাধ্যতামূলক করতে হবে।
4. **Single-node Swarm** — multi-node হলে overlay network encryption
   (`--opt encrypted`) ও manager quorum নিয়ে আলাদাভাবে ভাবতে হবে।
5. **Swarm secrets immutable** — secret rotate করতে নতুন নামে secret
   বানিয়ে service update করতে হয়। Production-এ HashiCorp Vault বা cloud
   secret manager দিয়ে এটা আরও gracefully handle করা উচিত।
6. **Traefik dashboard (port 8081) insecure mode-এ খোলা** — শুধু local
   demo debugging-এর জন্য; production-এ এটা বন্ধ বা আলাদা secured
   network-এ রাখতে হবে।

**যদি একটাই জিনিস প্রথমে ঠিক করতে হতো (production যাওয়ার আগে):** TLS
চালু করা এবং Grafana-কে edge-এর পেছনে নিয়ে যাওয়া — কারণ বর্তমানে এই দুইটাই
সবচেয়ে সরাসরি externally-visible gap, বাকিগুলো internal architecture
নিয়ে যা zero-day exposure না।
