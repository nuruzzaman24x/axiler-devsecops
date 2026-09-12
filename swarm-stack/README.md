# Docker Swarm Stack — Network Boundary + Deployment

এটা assignment-এর **ধাপ ৩ (Docker Swarm stack + network boundary)** এর জন্য।
এটা আগের `app-skeleton` (ধাপ ২) কে deploy করে, সাথে edge/internal network
আলাদা করে দেখায়।

## এখানে কী আছে

| File | কাজ |
|---|---|
| `docker-stack.yml` | পুরো stack definition — service, network, secret, update/rollback policy |
| `deploy.sh` | Image build + secret তৈরি + stack deploy, এক কমান্ডে |
| `teardown.sh` | Stack সরিয়ে ফেলা |
| `demo_bad_deploy.sh` | Scenario 2 demo — খারাপ version দিয়ে auto-rollback দেখানো |
| `verify_network_boundary.sh` | প্রমাণ করে app service সরাসরি বাইরে থেকে reachable না |

## Network Boundary — কীভাবে কাজ করে

```
                    external client
                          |
                          v
                  ┌───────────────┐
                  │   edge-net    │   <- শুধু এই network-এর port publish করা (80, 8081)
                  │  (overlay)    │
                  └───────┬───────┘
                          │
                    ┌─────▼─────┐
                    │  traefik  │   <- দুই network-এই আছে, একমাত্র entry point
                    └─────┬─────┘
                          │
                  ┌───────▼───────┐
                  │   app-net     │   <- কোনো published port নেই, বাইরে থেকে
                  │  (overlay)    │      কোনোভাবেই সরাসরি reachable না
                  └───────┬───────┘
                          │
                    ┌─────▼─────┐
                    │ app (x2)  │
                    └───────────┘
```

**মূল কথা:** `app` service-টা `app-net`-এ আছে, `edge-net`-এ নেই, আর কোনো
port publish করা নেই। তাই client চাইলেও সরাসরি app-এ পৌঁছাতে পারবে না —
সব ট্রাফিক বাধ্যতামূলকভাবে Traefik দিয়ে যেতে হবে। এটাই "backend services
private রাখা, external client শুধু controlled edge path ব্যবহার করবে"
requirement-এর বাস্তবায়ন — শুধু ডায়াগ্রামে না, actual config-এ enforced।

## Rollback strategy (Scenario 2 এর ভিত্তি)

`docker-stack.yml`-এ:
```yaml
update_config:
  failure_action: rollback
  monitor: 15s
  max_failure_ratio: 0
```
মানে: নতুন version deploy করার পর ১৫ সেকেন্ড Swarm নিজে monitor করবে
(healthcheck সহ)। কোনো task fail করলে (`max_failure_ratio: 0` মানে একটাও
failure সহ্য হবে না) **Swarm নিজে থেকেই আগের version-এ rollback করবে** —
কোনো ম্যানুয়াল হস্তক্ষেপ ছাড়াই। Manual rollback দরকার হলে:
```bash
docker service rollback axiler_app
```

## চালানোর ধাপ

```bash
cd swarm-stack
chmod +x *.sh
./deploy.sh
```

তারপর verify করো:
```bash
./verify_network_boundary.sh
```

আগের ধাপের smoke test চালাও (edge দিয়ে, port 80-এ):
```bash
export BASE_URL=http://localhost:80
export JWT_SECRET=devsecret123
bash ../app-skeleton/tests/smoke_test.sh
```

Bad-deployment / rollback demo (Scenario 2):
```bash
./demo_bad_deploy.sh
```

বন্ধ করতে:
```bash
./teardown.sh
```

## Secrets সম্পর্কে নোট

- `JWT_SECRET` এখন আর plain env var না — Docker Swarm secret হিসেবে
  `/run/secrets/jwt_secret`-এ mount হয়, app সেটা file থেকে পড়ে (`JWT_SECRET_FILE`)।
- Swarm secrets **immutable** — মান বদলাতে চাইলে নতুন নামে secret বানিয়ে
  (`jwt_secret_v2`) service update করতে হয়। এটা production-এ Vault বা
  external secret manager দিয়ে আরও ভালোভাবে করা উচিত — এটা design
  note-এ "known shortcut" হিসেবে উল্লেখ করবে।

## Known shortcuts (local demo-র জন্য, production না)

- Traefik dashboard পোর্ট (8081) খোলা রাখা হয়েছে দেখার সুবিধার জন্য —
  production-এ এটা বন্ধ বা আলাদা secured network-এ রাখতে হবে।
- Single-node Swarm ধরে নেওয়া হয়েছে; multi-node হলে placement constraints,
  overlay network encryption (`--opt encrypted`), এবং manager quorum
  নিয়ে আলাদা চিন্তা করতে হবে।
- TLS/HTTPS বাদ দেওয়া হয়েছে সরলতার জন্য — production-এ Traefik-এ
  Let's Encrypt বা internal CA দিয়ে TLS বাধ্যতামূলক করতে হবে।

## পরের ধাপ

- ধাপ ৪: Traefik-এ rate-limiting এবং edge-level auth/policy control যোগ করা
- ধাপ ৫: CI/CD pipeline যেটা এই ইমেজ build করে scan/sign করে registry-তে পাঠাবে
