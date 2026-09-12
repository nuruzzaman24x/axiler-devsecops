"""
Secure Multi-Tenant Transaction Platform — Application Skeleton
-----------------------------------------------------------------
This is a deliberately small, synthetic service that demonstrates:
  - JWT-based tenant identity (the trust anchor)
  - Tenant isolation enforced in code (not just by convention)
  - Search / Transfer / Health endpoints with realistic-but-fake data

Run locally:
    pip install -r requirements.txt
    export JWT_SECRET=devsecret123
    python app/main.py

In production / Swarm, set JWT_SECRET_FILE to point at the mounted
Docker secret instead (see docker-stack.yml). JWT_SECRET_FILE takes
priority over JWT_SECRET when both are present.

Then use tests/generate_token.py to create a test JWT for a tenant.
"""

import os
import time
import uuid
import logging
from functools import wraps

import jwt
from flask import Flask, request, jsonify, g

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _load_jwt_secret():
    """
    Resolve the JWT signing secret.

    Priority:
      1. JWT_SECRET_FILE — path to a mounted secret (e.g. Docker Swarm
         secret at /run/secrets/jwt_secret). Used in production/Swarm.
      2. JWT_SECRET — plain env var, for local dev only.

    If neither is set, we refuse to start rather than silently falling
    back to an insecure hardcoded default. A misconfigured deployment
    should fail loudly, not run with a known/guessable secret.
    """
    secret_file = os.environ.get("JWT_SECRET_FILE")
    if secret_file:
        try:
            with open(secret_file, "r") as f:
                return f.read().strip()
        except OSError as e:
            raise RuntimeError(
                f"JWT_SECRET_FILE is set to '{secret_file}' but the file "
                f"could not be read: {e}"
            )

    env_secret = os.environ.get("JWT_SECRET")
    if env_secret:
        return env_secret

    raise RuntimeError(
        "No JWT secret configured. Set JWT_SECRET_FILE (production/Swarm, "
        "points at a mounted secret file) or JWT_SECRET (local dev only, "
        "plain env var). Refusing to start with an insecure default."
    )


JWT_SECRET = _load_jwt_secret()
JWT_ALGORITHM = "HS256"
SERVICE_VERSION = os.environ.get("SERVICE_VERSION", "0.1.0-dev")

app = Flask(__name__)

# Structured logging (JSON-ish) so an operator can grep/filter by tenant,
# request_id, and version later in Loki/CloudWatch/etc.
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)
logger = logging.getLogger("txn-platform")

# ---------------------------------------------------------------------------
# Fake "database" — deliberately simple, keyed by tenant_id first.
# This is the actual isolation boundary: every lookup MUST go through
# a tenant-scoped dictionary. There is no global accounts table that a
# handler could accidentally query without a tenant filter.
# ---------------------------------------------------------------------------

FAKE_DB = {
    "alpha": {
        "ACC-1001": {"owner": "Alpha Client A", "balance": 5000.00},
        "ACC-1002": {"owner": "Alpha Client B", "balance": 1200.50},
    },
    "beta": {
        "ACC-2001": {"owner": "Beta Client A", "balance": 8300.00},
    },
    "gamma": {
        "ACC-3001": {"owner": "Gamma Client A", "balance": 450.75},
    },
}

# ---------------------------------------------------------------------------
# Tenant identity: this is the core trust decision for the whole platform.
#
# WHY A JWT AND NOT JUST A HEADER:
#   A raw "X-Tenant-ID: alpha" header is just a claim by the caller — anyone
#   could set that header to "beta" and see Beta's data. Instead, tenant
#   identity must be *asserted by something the platform trusts* (here: a
#   JWT signed with a secret only the edge/issuer knows). The application
#   never trusts a client-supplied tenant id directly; it only trusts the
#   tenant_id extracted from a verified token signature.
#
# In production this JWT would typically be issued by the SSE edge / an
# identity provider after authenticating the caller (mTLS, API key exchange,
# OAuth client credentials, etc.), not minted by the client itself.
# ---------------------------------------------------------------------------


def require_tenant(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        request_id = str(uuid.uuid4())
        g.request_id = request_id

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning(
                'auth_failed reason="missing_bearer_token" request_id="%s" path="%s"',
                request_id, request.path,
            )
            return jsonify({"error": "missing_or_invalid_authorization_header"}), 401

        token = auth_header.split(" ", 1)[1]

        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except jwt.ExpiredSignatureError:
            logger.warning(
                'auth_failed reason="token_expired" request_id="%s"', request_id
            )
            return jsonify({"error": "token_expired"}), 401
        except jwt.InvalidTokenError:
            logger.warning(
                'auth_failed reason="invalid_signature" request_id="%s" path="%s"',
                request_id, request.path,
            )
            # This is the exact log line an on-call engineer / SIEM would
            # alert on for "suspicious traffic" — Scenario 3 in the assignment.
            return jsonify({"error": "invalid_token"}), 403

        tenant_id = payload.get("tenant_id")
        if not tenant_id or tenant_id not in FAKE_DB:
            logger.warning(
                'auth_failed reason="unknown_tenant" tenant_id="%s" request_id="%s"',
                tenant_id, request_id,
            )
            return jsonify({"error": "unknown_tenant"}), 403

        # From here on, g.tenant_id is the ONLY source of truth for tenant
        # scoping in this request. Handlers must never read tenant id from
        # query params or headers.
        g.tenant_id = tenant_id
        logger.info(
            'request_authenticated tenant_id="%s" request_id="%s" path="%s"',
            tenant_id, request_id, request.path,
        )
        return f(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


FAIL_HEALTH = os.environ.get("FAIL_HEALTH", "false").lower() == "true"


@app.route("/health", methods=["GET"])
def health():
    # FAIL_HEALTH lets you deploy a deliberately broken version to
    # demonstrate Scenario 2 (bad deployment -> detection -> rollback)
    # without changing any code — just set the env var differently.
    if FAIL_HEALTH:
        return jsonify({"status": "error", "reason": "simulated_failure"}), 500
    return jsonify({
        "status": "ok",
        "version": SERVICE_VERSION,
        "time": time.time(),
    }), 200


@app.route("/search", methods=["GET"])
@require_tenant
def search():
    account_id = request.args.get("account")
    if not account_id:
        return jsonify({"error": "missing_account_param"}), 400

    tenant_accounts = FAKE_DB.get(g.tenant_id, {})
    account = tenant_accounts.get(account_id)

    if not account:
        # Deliberately generic: we don't reveal whether the account exists
        # under a DIFFERENT tenant. That would leak cross-tenant information.
        logger.info(
            'search_not_found tenant_id="%s" account_id="%s" request_id="%s"',
            g.tenant_id, account_id, g.request_id,
        )
        return jsonify({"error": "account_not_found"}), 404

    logger.info(
        'search_ok tenant_id="%s" account_id="%s" request_id="%s"',
        g.tenant_id, account_id, g.request_id,
    )
    return jsonify({
        "tenant_id": g.tenant_id,
        "account_id": account_id,
        "owner": account["owner"],
        "balance": account["balance"],
        "version": SERVICE_VERSION,
    }), 200


@app.route("/transfer", methods=["POST"])
@require_tenant
def transfer():
    body = request.get_json(silent=True) or {}
    from_account = body.get("from_account")
    to_account = body.get("to_account")
    amount = body.get("amount")

    if not from_account or not to_account or amount is None:
        return jsonify({"error": "missing_fields", "required": ["from_account", "to_account", "amount"]}), 400

    tenant_accounts = FAKE_DB.get(g.tenant_id, {})

    # Isolation check: BOTH accounts in a transfer must belong to the
    # calling tenant. This prevents Tenant A from moving money into or
    # out of Tenant B's accounts even if they guess a valid account id.
    if from_account not in tenant_accounts or to_account not in tenant_accounts:
        logger.warning(
            'transfer_denied reason="cross_tenant_or_unknown_account" '
            'tenant_id="%s" from="%s" to="%s" request_id="%s"',
            g.tenant_id, from_account, to_account, g.request_id,
        )
        return jsonify({"error": "invalid_account_for_tenant"}), 403

    if tenant_accounts[from_account]["balance"] < amount:
        return jsonify({"error": "insufficient_funds"}), 400

    tenant_accounts[from_account]["balance"] -= amount
    tenant_accounts[to_account]["balance"] += amount

    logger.info(
        'transfer_ok tenant_id="%s" from="%s" to="%s" amount="%s" request_id="%s"',
        g.tenant_id, from_account, to_account, amount, g.request_id,
    )

    return jsonify({
        "status": "completed",
        "tenant_id": g.tenant_id,
        "from_account": from_account,
        "to_account": to_account,
        "amount": amount,
        "version": SERVICE_VERSION,
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)







# """
# Secure Multi-Tenant Transaction Platform — Application Skeleton
# -----------------------------------------------------------------
# This is a deliberately small, synthetic service that demonstrates:
#   - JWT-based tenant identity (the trust anchor)
#   - Tenant isolation enforced in code (not just by convention)
#   - Search / Transfer / Health endpoints with realistic-but-fake data

# Run locally:
#     pip install -r requirements.txt
#     export JWT_SECRET=devsecret123
#     python app/main.py

# Then use tests/generate_token.py to create a test JWT for a tenant.
# """

# import os
# import time
# import uuid
# import logging
# from functools import wraps

# import jwt
# from flask import Flask, request, jsonify, g

# # ---------------------------------------------------------------------------
# # Configuration
# # ---------------------------------------------------------------------------

# JWT_SECRET = os.environ.get("JWT_SECRET", "devsecret123")
# JWT_ALGORITHM = "HS256"
# SERVICE_VERSION = os.environ.get("SERVICE_VERSION", "0.1.0-dev")

# app = Flask(__name__)

# # Structured logging (JSON-ish) so an operator can grep/filter by tenant,
# # request_id, and version later in Loki/CloudWatch/etc.
# logging.basicConfig(
#     level=logging.INFO,
#     format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
# )
# logger = logging.getLogger("txn-platform")

# # ---------------------------------------------------------------------------
# # Fake "database" — deliberately simple, keyed by tenant_id first.
# # This is the actual isolation boundary: every lookup MUST go through
# # a tenant-scoped dictionary. There is no global accounts table that a
# # handler could accidentally query without a tenant filter.
# # ---------------------------------------------------------------------------

# FAKE_DB = {
#     "alpha": {
#         "ACC-1001": {"owner": "Alpha Client A", "balance": 5000.00},
#         "ACC-1002": {"owner": "Alpha Client B", "balance": 1200.50},
#     },
#     "beta": {
#         "ACC-2001": {"owner": "Beta Client A", "balance": 8300.00},
#     },
#     "gamma": {
#         "ACC-3001": {"owner": "Gamma Client A", "balance": 450.75},
#     },
# }

# # ---------------------------------------------------------------------------
# # Tenant identity: this is the core trust decision for the whole platform.
# #
# # WHY A JWT AND NOT JUST A HEADER:
# #   A raw "X-Tenant-ID: alpha" header is just a claim by the caller — anyone
# #   could set that header to "beta" and see Beta's data. Instead, tenant
# #   identity must be *asserted by something the platform trusts* (here: a
# #   JWT signed with a secret only the edge/issuer knows). The application
# #   never trusts a client-supplied tenant id directly; it only trusts the
# #   tenant_id extracted from a verified token signature.
# #
# # In production this JWT would typically be issued by the SSE edge / an
# # identity provider after authenticating the caller (mTLS, API key exchange,
# # OAuth client credentials, etc.), not minted by the client itself.
# # ---------------------------------------------------------------------------


# def require_tenant(f):
#     @wraps(f)
#     def wrapper(*args, **kwargs):
#         request_id = str(uuid.uuid4())
#         g.request_id = request_id

#         auth_header = request.headers.get("Authorization", "")
#         if not auth_header.startswith("Bearer "):
#             logger.warning(
#                 'auth_failed reason="missing_bearer_token" request_id="%s" path="%s"',
#                 request_id, request.path,
#             )
#             return jsonify({"error": "missing_or_invalid_authorization_header"}), 401

#         token = auth_header.split(" ", 1)[1]

#         try:
#             payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
#         except jwt.ExpiredSignatureError:
#             logger.warning(
#                 'auth_failed reason="token_expired" request_id="%s"', request_id
#             )
#             return jsonify({"error": "token_expired"}), 401
#         except jwt.InvalidTokenError:
#             logger.warning(
#                 'auth_failed reason="invalid_signature" request_id="%s" path="%s"',
#                 request_id, request.path,
#             )
#             # This is the exact log line an on-call engineer / SIEM would
#             # alert on for "suspicious traffic" — Scenario 3 in the assignment.
#             return jsonify({"error": "invalid_token"}), 403

#         tenant_id = payload.get("tenant_id")
#         if not tenant_id or tenant_id not in FAKE_DB:
#             logger.warning(
#                 'auth_failed reason="unknown_tenant" tenant_id="%s" request_id="%s"',
#                 tenant_id, request_id,
#             )
#             return jsonify({"error": "unknown_tenant"}), 403

#         # From here on, g.tenant_id is the ONLY source of truth for tenant
#         # scoping in this request. Handlers must never read tenant id from
#         # query params or headers.
#         g.tenant_id = tenant_id
#         logger.info(
#             'request_authenticated tenant_id="%s" request_id="%s" path="%s"',
#             tenant_id, request_id, request.path,
#         )
#         return f(*args, **kwargs)

#     return wrapper


# # ---------------------------------------------------------------------------
# # Endpoints
# # ---------------------------------------------------------------------------


# FAIL_HEALTH = os.environ.get("FAIL_HEALTH", "false").lower() == "true"


# @app.route("/health", methods=["GET"])
# def health():
#     # FAIL_HEALTH lets you deploy a deliberately broken version to
#     # demonstrate Scenario 2 (bad deployment -> detection -> rollback)
#     # without changing any code — just set the env var differently.
#     if FAIL_HEALTH:
#         return jsonify({"status": "error", "reason": "simulated_failure"}), 500
#     return jsonify({
#         "status": "ok",
#         "version": SERVICE_VERSION,
#         "time": time.time(),
#     }), 200


# @app.route("/search", methods=["GET"])
# @require_tenant
# def search():
#     account_id = request.args.get("account")
#     if not account_id:
#         return jsonify({"error": "missing_account_param"}), 400

#     tenant_accounts = FAKE_DB.get(g.tenant_id, {})
#     account = tenant_accounts.get(account_id)

#     if not account:
#         # Deliberately generic: we don't reveal whether the account exists
#         # under a DIFFERENT tenant. That would leak cross-tenant information.
#         logger.info(
#             'search_not_found tenant_id="%s" account_id="%s" request_id="%s"',
#             g.tenant_id, account_id, g.request_id,
#         )
#         return jsonify({"error": "account_not_found"}), 404

#     logger.info(
#         'search_ok tenant_id="%s" account_id="%s" request_id="%s"',
#         g.tenant_id, account_id, g.request_id,
#     )
#     return jsonify({
#         "tenant_id": g.tenant_id,
#         "account_id": account_id,
#         "owner": account["owner"],
#         "balance": account["balance"],
#         "version": SERVICE_VERSION,
#     }), 200


# @app.route("/transfer", methods=["POST"])
# @require_tenant
# def transfer():
#     body = request.get_json(silent=True) or {}
#     from_account = body.get("from_account")
#     to_account = body.get("to_account")
#     amount = body.get("amount")

#     if not from_account or not to_account or amount is None:
#         return jsonify({"error": "missing_fields", "required": ["from_account", "to_account", "amount"]}), 400

#     tenant_accounts = FAKE_DB.get(g.tenant_id, {})

#     # Isolation check: BOTH accounts in a transfer must belong to the
#     # calling tenant. This prevents Tenant A from moving money into or
#     # out of Tenant B's accounts even if they guess a valid account id.
#     if from_account not in tenant_accounts or to_account not in tenant_accounts:
#         logger.warning(
#             'transfer_denied reason="cross_tenant_or_unknown_account" '
#             'tenant_id="%s" from="%s" to="%s" request_id="%s"',
#             g.tenant_id, from_account, to_account, g.request_id,
#         )
#         return jsonify({"error": "invalid_account_for_tenant"}), 403

#     if tenant_accounts[from_account]["balance"] < amount:
#         return jsonify({"error": "insufficient_funds"}), 400

#     tenant_accounts[from_account]["balance"] -= amount
#     tenant_accounts[to_account]["balance"] += amount

#     logger.info(
#         'transfer_ok tenant_id="%s" from="%s" to="%s" amount="%s" request_id="%s"',
#         g.tenant_id, from_account, to_account, amount, g.request_id,
#     )

#     return jsonify({
#         "status": "completed",
#         "tenant_id": g.tenant_id,
#         "from_account": from_account,
#         "to_account": to_account,
#         "amount": amount,
#         "version": SERVICE_VERSION,
#     }), 200


# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=8080)
