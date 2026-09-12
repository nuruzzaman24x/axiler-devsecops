# AI Usage Disclosure

## কোন AI tool ব্যবহার করা হয়েছে

- **Claude (chat)** — architecture-এর সিদ্ধান্ত নেওয়ার আগে বোঝাপড়া
  (trade-off আলোচনা, PromQL query ব্যাখ্যা, Grafana alert-rule UI নেভিগেট
  করা), এবং documentation (README, design note, diagram) লেখায় ভাষা
  গোছানো।
- **Claude Code** — actual কোড/কনফিগ লেখা এবং চালানো: Flask app skeleton
  (`app/main.py`), Dockerfile, Docker Swarm stack file
  (`docker-stack.yml`), Traefik rate-limit config, GitHub Actions
  CI/CD workflow, Prometheus scrape config, deploy/teardown/demo script।

কাজের ভাগ: architecture সিদ্ধান্ত, review, এবং defend করা — এই repo-র
মালিকের (আমার) কাজ। Actual code লেখা, চালানো, টেস্ট করা — Claude Code-এর
কাজ, যেটা আমি প্রতিটা ধাপে review করেছি।

## Concrete উদাহরণ — একটা AI suggestion যেটা verify করে correct করা হয়েছে

**প্রেক্ষাপট:** ধাপ ৬ (Secrets ও least privilege)-এ, `docker-stack.yml`-এ
Docker Swarm secret ব্যবহার করে JWT secret দেওয়ার কথা ছিল, plaintext env
var-এর বদলে। Claude Code `docker-stack.yml`-এ `JWT_SECRET_FILE` env var
ঠিকভাবে সেট করে দিয়েছিল, secret mount-ও ঠিক ছিল।

**যে ভুলটা ধরা পড়েছিল:** `app/main.py`-এর প্রথম ভার্সনে কোড আসলে
`JWT_SECRET_FILE` পড়তই না — শুধু `JWT_SECRET` env var (এবং সেটাও না থাকলে
hardcoded `"devsecret123"`) ব্যবহার করত:
```python
JWT_SECRET = os.environ.get("JWT_SECRET", "devsecret123")
```
মানে stack file-এ secret সঠিকভাবে mount হলেও, app চুপচাপ সেই mounted
secret-কে ignore করে hardcoded insecure default-এই fallback করছিল —
config আর কোড দুটো একে অপরের সাথে সামঞ্জস্যপূর্ণ ছিল না।

**কীভাবে ধরা পড়লো:** stack file আর app কোড পাশাপাশি manually পড়ে
verify করার সময় — `docker-stack.yml`-এ secret path আর `main.py`-এর env
var read লজিক মিলিয়ে দেখতে গিয়ে এই gap চোখে পড়ে। এটা টেস্ট চালিয়ে ধরা
পড়েনি (কারণ local dev-এ `JWT_SECRET` env var সেট করা থাকলে সবকিছু
"কাজ করে" বলেই মনে হতো), শুধু কোড রিভিউ করেই ধরা পড়েছে।

**সমাধান:** `_load_jwt_secret()` নামে একটা ফাংশন লিখে ঠিক করা হয়েছে, যেখানে
priority হলো: `JWT_SECRET_FILE` (থাকলে, file থেকে পড়ে) → `JWT_SECRET`
(local dev fallback) → **কোনোটাই না থাকলে app startup-এই fail করে**
(`RuntimeError`), silent insecure default-এ চুপচাপ না চলে।

**এই থেকে শেখা:** AI-generated কোড আলাদা আলাদাভাবে "সঠিক" মনে হতে পারে
(stack file ঠিক, app কোডও চলে) অথচ দুটোর মধ্যে integration gap থাকতে
পারে যা শুধু runtime টেস্টে ধরা পড়ে না — বিশেষ করে যেখানে একটা silent
fallback আছে যা error না ফেলে ভুলভাবে "সফলভাবে" চলে। তাই security-critical
config (secrets, auth) সবসময় end-to-end manually verify করা দরকার,
শুধু "কোড চলছে" দেখেই সন্তুষ্ট হওয়া যথেষ্ট না।
