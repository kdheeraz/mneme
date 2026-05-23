"""Open-core licensing for self-hosted Mneme.

Community (no/invalid/expired license) runs the full core for free, capped at
`settings.community_max_users` accounts per instance. A signed Business/Enterprise
license (env MNEME_LICENSE_KEY, or a file at MNEME_LICENSE_FILE) lifts the cap and
unlocks Business features.

Licenses are EdDSA-signed JWTs verified OFFLINE against the embedded public key —
no phone-home, works air-gapped. The private signing key lives only with the vendor
(see backend/tools/issue_license.py); it is never shipped in the repo.
"""
from __future__ import annotations

import os
from typing import Optional

import jwt

from .config import settings

# Vendor public key — verify only. Issuing licenses needs the matching private key.
LICENSE_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAtyT9F525AIVoays8vPHFJmToV1SamPeRONbQrssFpGA=
-----END PUBLIC KEY-----"""


def _raw_key() -> str:
    key = (os.environ.get("MNEME_LICENSE_KEY") or "").strip()
    if key:
        return key
    path = (os.environ.get("MNEME_LICENSE_FILE") or "").strip()
    if path and os.path.exists(path):
        try:
            return open(path).read().strip()
        except Exception:
            return ""
    return ""


def _community(note: Optional[str] = None) -> dict:
    return {
        "valid": True,
        "tier": "community",
        "customer": None,
        "expires_at": None,
        "features": [],
        "max_users": settings.community_max_users,
        "note": note,
    }


def get_license() -> dict:
    """Resolve the active license. Always returns a dict (never raises);
    falls back to community on missing/invalid/expired keys."""
    token = _raw_key()
    if not token:
        return _community()
    try:
        claims = jwt.decode(token, LICENSE_PUBLIC_KEY, algorithms=["EdDSA"])
    except jwt.ExpiredSignatureError:
        return _community("license expired — running in community mode")
    except Exception:
        return _community("invalid license — running in community mode")
    return {
        "valid": True,
        "tier": claims.get("tier", "business"),
        "customer": claims.get("sub"),
        "expires_at": claims.get("exp"),
        "features": claims.get("features") or [],
        "max_users": claims.get("max_users"),  # None / absent = unlimited
        "note": None,
    }


def tier() -> str:
    return get_license()["tier"]


def is_licensed() -> bool:
    return get_license()["tier"] != "community"


def has_feature(name: str) -> bool:
    lic = get_license()
    if lic["tier"] == "community":
        return False
    feats = lic.get("features") or []
    return name in feats or "all" in feats


def max_users() -> Optional[int]:
    """Per-instance account cap. None = unlimited (Business/Enterprise)."""
    return get_license().get("max_users")
