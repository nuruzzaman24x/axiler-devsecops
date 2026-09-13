#!/usr/bin/env bash
# Demonstrates that Traefik's rate-limit middleware (average=5/s, burst=10)
# actually rejects requests once exceeded — part of Scenario 3
# (abusive request burst).
set -e

TOKEN=$(python3 ../app-skeleton/tests/generate_token.py alpha)

echo "== Firing 30 rapid requests through the edge (http://localhost:80) =="
echo "Expect a mix of 200s (allowed) and 429s (rate-limited) once the burst is exceeded."
echo

for i in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer $TOKEN" \
        "http://localhost:80/search?account=ACC-1001")
    echo -n "$code "
done
echo
echo
echo "If you see 429s appear, rate limiting is active."
echo "Check the metric in Prometheus (http://localhost:9090):"
echo '  sum(rate(traefik_entrypoint_requests_total{code="429"}[1m]))'
echo "The EdgeRateLimitingActive alert (see alert_rules.yml) should also go Pending/Firing."
