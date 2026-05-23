"""API key auth. Resolves a key → (tenant, optional bound agent_slug)."""
import secrets
from datetime import datetime, timezone
from typing import Optional, Tuple
from dataclasses import dataclass

from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session

from .db import get_db
from .models import ApiKey, Tenant, Agent
from .auth_user import decode_jwt


def new_api_key(prefix: str = "mneme_sk") -> str:
    return f"{prefix}_" + secrets.token_urlsafe(32)


@dataclass
class KeyContext:
    tenant: Tenant
    api_key: ApiKey
    bound_agent_slug: Optional[str]  # set if key is agent-scoped


def require_key(
    x_api_key: str = Header(default=""),
    db: Session = Depends(get_db),
) -> KeyContext:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key header")
    row = db.query(ApiKey).filter(ApiKey.key == x_api_key).first()
    if not row:
        raise HTTPException(status_code=401, detail="invalid api key")
    tenant = db.query(Tenant).filter(Tenant.id == row.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=401, detail="tenant not found")

    # touch last_used_at
    row.last_used_at = datetime.now(timezone.utc)
    db.commit()

    return KeyContext(tenant=tenant, api_key=row, bound_agent_slug=row.agent_slug)


def tenant_from_any_auth(
    x_api_key: str = Header(default=""),
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> Tenant:
    """Resolve a tenant from EITHER an API key or a JWT. Used for read-only,
    tenant-scoped endpoints (traces, stats) that both the dashboard (JWT) and the
    SDK (X-API-Key) need to call."""
    if x_api_key:
        row = db.query(ApiKey).filter(ApiKey.key == x_api_key).first()
        if row:
            t = db.query(Tenant).filter(Tenant.id == row.tenant_id).first()
            if t:
                return t
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = decode_jwt(token)
            t = db.query(Tenant).filter(Tenant.id == payload["tenant"]).first()
            if t:
                return t
        except Exception:
            pass
    raise HTTPException(status_code=401, detail="auth required (X-API-Key or Bearer token)")


def resolve_agent_for_write(ctx: KeyContext, body_agent_id: Optional[str], db: Session) -> Optional[Agent]:
    """Pick the agent for a write operation.
    - If key is agent-scoped, body_agent_id is ignored (or must match).
    - Otherwise, body_agent_id (a slug) is used; agent must exist in tenant.
    Returns Agent or None (None only if neither key nor body specify, which is allowed
    for tenant-wide memories like shared knowledge).
    """
    slug = ctx.bound_agent_slug or body_agent_id
    if not slug:
        return None
    agent = (
        db.query(Agent)
        .filter(Agent.tenant_id == ctx.tenant.id, Agent.slug == slug)
        .first()
    )
    if not agent:
        raise HTTPException(404, f"agent '{slug}' not registered in this tenant")
    return agent
