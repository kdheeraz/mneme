"""User auth: signup, login, JWT, password hashing, secret encryption."""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from uuid import UUID

import bcrypt
import jwt
from cryptography.fernet import Fernet
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session

from .config import settings, get_fernet_key
from .db import get_db
from .models import User, Tenant


# -------- passwords --------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# -------- JWT --------

def issue_jwt(user_id: UUID, tenant_id: UUID) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_hours)
    payload = {"sub": str(user_id), "tenant": str(tenant_id), "exp": exp}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def decode_jwt(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])


# -------- secret encryption (per-agent LLM/embedding keys) --------

_fernet = Fernet(get_fernet_key())


def encrypt_secret(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return _fernet.encrypt(s.encode()).decode()


def decrypt_secret(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        return _fernet.decrypt(s.encode()).decode()
    except Exception:
        return None


# -------- FastAPI dependency: current user + tenant --------

def current_user(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> Tuple[User, Tenant]:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_jwt(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "invalid token")

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(401, "user not found")
    if getattr(user, "disabled", False):
        raise HTTPException(403, "account disabled")
    tenant = db.query(Tenant).filter(Tenant.id == payload["tenant"]).first()
    if not tenant:
        raise HTTPException(401, "tenant not found")
    return user, tenant
