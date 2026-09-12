#!/usr/bin/env bash
# Manual smoke test for the app skeleton.
# Run the app first: python app/main.py  (or via Docker, mapped to :8080)

set -e
BASE_URL="${BASE_URL:-http://localhost:8080}"

echo "== Generating tokens =="
ALPHA_TOKEN=$(python tests/generate_token.py alpha)
BETA_TOKEN=$(python tests/generate_token.py beta)

echo
echo "== Health check =="
curl -s "$BASE_URL/health" | python -m json.tool

echo
echo "== Alpha searches its own account (expect 200) =="
curl -s -H "Authorization: Bearer $ALPHA_TOKEN" "$BASE_URL/search?account=ACC-1001" | python -m json.tool

echo
echo "== Alpha tries to search Beta's account (expect 404 - not visible cross-tenant) =="
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $ALPHA_TOKEN" "$BASE_URL/search?account=ACC-2001"

echo
echo "== Alpha tries to transfer FROM its own account TO Beta's account (expect 403 - cross-tenant denied) =="
curl -s -X POST -H "Authorization: Bearer $ALPHA_TOKEN" -H "Content-Type: application/json" \
    -d '{"from_account":"ACC-1001","to_account":"ACC-2001","amount":100}' \
    "$BASE_URL/transfer" | python -m json.tool

echo
echo "== Request with NO token (expect 401) - Scenario 3: suspicious/unauthorized traffic =="
curl -s -o /dev/null -w "%{http_code}\n" "$BASE_URL/search?account=ACC-1001"

echo
echo "== Request with GARBAGE token (expect 403) - Scenario 3 =="
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer not-a-real-token" "$BASE_URL/search?account=ACC-1001"

echo
echo "Done. Check the application logs for the corresponding auth_failed / transfer_denied entries."
