"""Vendor-side Mneme license issuer (EdDSA-signed JWT).

Keep the private signing key SECRET — it lives only with the vendor and must never
be committed or shipped. Customers verify offline with the public key embedded in
backend/app/license.py.

Usage (run from the backend/ dir, or pass --key):
  python tools/issue_license.py --customer "Acme Inc" --tier business --days 365 \
      --features sso,audit,rbac --max-users 0
  # --max-users 0  -> unlimited accounts

Prints the license token; the customer sets it as MNEME_LICENSE_KEY.
"""
import argparse
import time

import jwt


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--customer", required=True, help="Customer/org name (license 'sub')")
    ap.add_argument("--tier", default="business", choices=["business", "enterprise"])
    ap.add_argument("--days", type=int, default=365, help="Validity in days")
    ap.add_argument("--features", default="", help="Comma-separated, e.g. sso,audit,rbac (or 'all')")
    ap.add_argument("--max-users", type=int, default=0, help="Per-instance account cap; 0 = unlimited")
    ap.add_argument("--key", default=".license_signing_key.pem", help="Path to the private signing key (PEM)")
    a = ap.parse_args()

    private_pem = open(a.key).read()
    now = int(time.time())
    claims = {
        "sub": a.customer,
        "tier": a.tier,
        "iat": now,
        "exp": now + a.days * 86400,
        "features": [f.strip() for f in a.features.split(",") if f.strip()],
    }
    if a.max_users > 0:
        claims["max_users"] = a.max_users  # omit => unlimited

    print(jwt.encode(claims, private_pem, algorithm="EdDSA"))


if __name__ == "__main__":
    main()
