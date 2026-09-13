# AI Usage Disclosure

## Which AI Tools Were Used

- **Claude (chat)** — for understanding trade-offs before making
  architecture decisions (discussing options, explaining PromQL queries,
  navigating the Grafana alert-rule UI), and for writing/polishing
  documentation (README, design note, diagrams).
- **Claude Code** — for writing and running the actual code/config: the
  Flask app skeleton (`app/main.py`), the Dockerfile, the Docker Swarm
  stack file (`docker-stack.yml`), the Traefik rate-limit config, the
  GitHub Actions CI/CD workflow, the Prometheus scrape config, and the
  deploy/teardown/demo scripts.

Division of work: architecture decisions, review, and defending the
design were mine. Writing, running, and testing the actual code was
Claude Code's job, reviewed by me at each step.

## Concrete Example — an AI Suggestion That Was Verified and Corrected

**Context:** for the secrets and least-privilege step, `docker-stack.yml`
was supposed to use a Docker Swarm secret for the JWT secret instead of a
plaintext environment variable. Claude Code correctly set the
`JWT_SECRET_FILE` environment variable in `docker-stack.yml`, and the
secret mount itself was correct.

**The bug that was caught:** in the first version of `app/main.py`, the
code never actually read `JWT_SECRET_FILE` — it only used the
`JWT_SECRET` env var (and fell back to a hardcoded `"devsecret123"` if
that wasn't set either):
```python
JWT_SECRET = os.environ.get("JWT_SECRET", "devsecret123")
```
This meant that even though the Swarm secret was correctly mounted, the
app was silently ignoring it and falling back to a hardcoded, insecure
default — the stack config and the application code were not actually
consistent with each other.

**How it was caught:** by manually reading the stack file and the app
code side by side and cross-checking the secret path in
`docker-stack.yml` against the env-var-reading logic in `main.py`. It was
not caught by running tests (because in local dev, having `JWT_SECRET`
set in the environment made everything "appear to work") — only by code
review.

**The fix:** written as a `_load_jwt_secret()` function with the
priority: `JWT_SECRET_FILE` (read from the mounted file if present) →
`JWT_SECRET` (local dev fallback) → **if neither is set, fail loudly at
startup** (`RuntimeError`), instead of silently falling back to an
insecure default.

**Takeaway:** AI-generated code can look correct in isolation (the stack
file was fine, the app code ran fine) while still having an integration
gap between the two that a runtime test alone won't catch — especially
when there's a silent fallback that "succeeds" without raising an error.
Security-critical configuration (secrets, auth) should always be verified
end-to-end manually, not just by observing that "the code runs."
