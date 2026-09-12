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
- Prometheus/Grafana observability
