"""
Generate a test JWT for a given tenant, signed with the same JWT_SECRET
the app uses. In production this token would be issued by the SSE edge /
identity provider after real authentication — this script exists ONLY to
let you exercise the API locally and in demo scenarios.

Usage:
    python tests/generate_token.py alpha
    python tests/generate_token.py beta
    python tests/generate_token.py nonexistent   # -> app will reject as unknown_tenant
"""

import sys
import os
import time
import jwt

JWT_SECRET = os.environ.get("JWT_SECRET", "devsecret123")


def main():
    if len(sys.argv) != 2:
        print("Usage: python generate_token.py <tenant_id>")
        sys.exit(1)

    tenant_id = sys.argv[1]
    payload = {
        "tenant_id": tenant_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,  # 1 hour
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    print(token)


if __name__ == "__main__":
    main()
