# Application Skeleton — Search / Transfer / Health

এটা assignment-এর **ধাপ ২ (Application skeleton)** এর জন্য একটা ready-to-use starter।
এটা পুরো assignment না — শুধু app layer। বাকি অংশ (Swarm, CI/CD, edge, observability)
এই skeleton-এর উপর ভিত্তি করে পরের ধাপে যোগ হবে।

## এখানে কী আছে

- `app/main.py` — Flask সার্ভিস: `/health`, `/search`, `/transfer`
- `tests/generate_token.py` — টেস্টের জন্য tenant JWT বানানোর script
- `tests/smoke_test.sh` — সব endpoint এবং isolation logic ম্যানুয়ালি ভেরিফাই করার script
- `Dockerfile` — non-root user, healthcheck সহ
- `requirements.txt`

## Tenant Trust Model (গুরুত্বপূর্ণ — interview-এ এটা explain করতে হবে)

1. Client একটা signed JWT পাঠায় `Authorization: Bearer <token>` header-এ।
2. Token-এর ভেতরে `tenant_id` claim থাকে।
3. App শুধুমাত্র **verified signature থেকে বের করা** `tenant_id` বিশ্বাস করে —
   কোনো header বা query param থেকে সরাসরি tenant_id নেয় না।
4. প্রতিটা ডেটা lookup (`FAKE_DB[tenant_id]`) tenant-scoped — তাই এক tenant-এর
   কোডপাথে গিয়েও অন্য tenant-এর ডেটা দেখা সম্ভব না।
5. Transfer-এর ক্ষেত্রে **both** from_account এবং to_account tenant-এর নিজের
   হতে হবে — নাহলে 403।

**Production-এ পার্থক্য:** এই স্ক্রিপ্টে token আমরা নিজেরাই বানাচ্ছি টেস্টের জন্য।
বাস্তবে এই token issue করবে SSE edge / identity provider, client-এর real
authentication (mTLS, OAuth client-credentials, ইত্যাদি) যাচাই করার পরে।
এই gap-টা design note-এ "known shortcut" হিসেবে উল্লেখ করতে হবে।

## JWT Secret Configuration (ধাপ ৬ — Secrets ও least privilege)

`JWT_SECRET` এখন দুইভাবে দেওয়া যায়, একটা priority order মেনে:

1. **`JWT_SECRET_FILE`** — একটা mounted secret file-এর path (production/Swarm-এর
   জন্য)। Docker Swarm secret হিসেবে `/run/secrets/jwt_secret`-এ mount হয়, app
   সরাসরি সেই file থেকে পড়ে। এটা সেট থাকলে সবসময় এটাই priority পায়।
2. **`JWT_SECRET`** — plain env var, শুধুমাত্র local dev-এর জন্য।
3. দুটোর একটাও না থাকলে app **startup-এই fail করে** (`RuntimeError`) — silent
   insecure hardcoded default দিয়ে চুপচাপ চলবে না।

**Bug fix নোট:** আগের ভার্সনে `docker-stack.yml`-এ `JWT_SECRET_FILE` env var সেট
করা থাকলেও `app/main.py` আসলে সেটা পড়তই না — কোড শুধু `JWT_SECRET` env var (এবং
না থাকলে hardcoded `"devsecret123"`) ব্যবহার করত। ফলে Swarm secret mount হলেও
app চুপচাপ সেই hardcoded default-এই fallback করত, secret আদৌ ব্যবহার হতো না।
এটা manually verify করে ধরা পড়েছে এবং `_load_jwt_secret()` ফাংশন দিয়ে ফিক্স করা
হয়েছে — এখন `JWT_SECRET_FILE` অগ্রাধিকার পায়, আর কোনো secret না পেলে app silently
চলার বদলে সাথে সাথে বন্ধ হয়ে যায়।

## চালানো (Local)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export JWT_SECRET=devsecret123
python app/main.py
```

আরেকটা টার্মিনালে:

```bash
export JWT_SECRET=devsecret123
bash tests/smoke_test.sh
```

## Docker দিয়ে চালানো

```bash
docker build -t txn-platform:dev .
docker run -p 8080:8080 -e JWT_SECRET=devsecret123 txn-platform:dev
```

Production/Swarm-স্টাইল (file-based secret) simulate করতে:

```bash
echo -n "devsecret123" > /tmp/fake_secret
docker run -p 8080:8080 \
  -v /tmp/fake_secret:/run/secrets/jwt_secret:ro \
  -e JWT_SECRET_FILE=/run/secrets/jwt_secret \
  txn-platform:dev
```

## Bad-deployment demo (Scenario 2 এর জন্য প্রস্তুত)

```bash
docker run -p 8080:8080 -e JWT_SECRET=devsecret123 -e FAIL_HEALTH=true txn-platform:dev
curl http://localhost:8080/health   # 500 ফেরত দেবে
```

এই flag পরে Swarm stack file-এ একটা "bad version" হিসেবে ব্যবহার করবে
rollback demonstrate করার জন্য।

## পরের ধাপ (এই skeleton-এর উপরে যা যোগ হবে)

- Docker Swarm stack file (network boundary সহ)
- Traefik/Nginx edge (rate limiting, JWT validation ফরওয়ার্ড)
- GitHub Actions CI/CD (scan, SBOM, sign, gate)
- Prometheus/Grafana observability









<!-- # Application Skeleton — Search / Transfer / Health

এটা assignment-এর **ধাপ ২ (Application skeleton)** এর জন্য একটা ready-to-use starter।
এটা পুরো assignment না — শুধু app layer। বাকি অংশ (Swarm, CI/CD, edge, observability)
এই skeleton-এর উপর ভিত্তি করে পরের ধাপে যোগ হবে।

## এখানে কী আছে

- `app/main.py` — Flask সার্ভিস: `/health`, `/search`, `/transfer`
- `tests/generate_token.py` — টেস্টের জন্য tenant JWT বানানোর script
- `tests/smoke_test.sh` — সব endpoint এবং isolation logic ম্যানুয়ালি ভেরিফাই করার script
- `Dockerfile` — non-root user, healthcheck সহ
- `requirements.txt`

## Tenant Trust Model (গুরুত্বপূর্ণ — interview-এ এটা explain করতে হবে)

1. Client একটা signed JWT পাঠায় `Authorization: Bearer <token>` header-এ।
2. Token-এর ভেতরে `tenant_id` claim থাকে।
3. App শুধুমাত্র **verified signature থেকে বের করা** `tenant_id` বিশ্বাস করে —
   কোনো header বা query param থেকে সরাসরি tenant_id নেয় না।
4. প্রতিটা ডেটা lookup (`FAKE_DB[tenant_id]`) tenant-scoped — তাই এক tenant-এর
   কোডপাথে গিয়েও অন্য tenant-এর ডেটা দেখা সম্ভব না।
5. Transfer-এর ক্ষেত্রে **both** from_account এবং to_account tenant-এর নিজের
   হতে হবে — নাহলে 403.

**Production-এ পার্থক্য:** এই স্ক্রিপ্টে token আমরা নিজেরাই বানাচ্ছি টেস্টের জন্য।
বাস্তবে এই token issue করবে SSE edge / identity provider, client-এর real
authentication (mTLS, OAuth client-credentials, ইত্যাদি) যাচাই করার পরে।
এই gap-টা design note-এ "known shortcut" হিসেবে উল্লেখ করতে হবে।

## চালানো (Local)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export JWT_SECRET=devsecret123
python app/main.py
```

আরেকটা টার্মিনালে:

```bash
export JWT_SECRET=devsecret123
bash tests/smoke_test.sh
```

## Docker দিয়ে চালানো

```bash
docker build -t txn-platform:dev .
docker run -p 8080:8080 -e JWT_SECRET=devsecret123 txn-platform:dev
```

## Bad-deployment demo (Scenario 2 এর জন্য প্রস্তুত)

```bash
docker run -p 8080:8080 -e JWT_SECRET=devsecret123 -e FAIL_HEALTH=true txn-platform:dev
curl http://localhost:8080/health   # 500 ফেরত দেবে
```

এই flag পরে Swarm stack file-এ একটা "bad version" হিসেবে ব্যবহার করবে
rollback demonstrate করার জন্য।

## পরের ধাপ (এই skeleton-এর উপরে যা যোগ হবে)

- Docker Swarm stack file (network boundary সহ)
- Traefik/Nginx edge (rate limiting, JWT validation ফরওয়ার্ড)
- GitHub Actions CI/CD (scan, SBOM, sign, gate)
- Prometheus/Grafana observability -->
