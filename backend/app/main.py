import time
import math
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func, desc, literal, or_
from sqlalchemy.orm import Session
from slugify import slugify

from .db import get_db, Base, engine
from .models import User, Tenant, Agent, ApiKey, Memory, Trace, GraphEntity, GraphRelation, ContactMessage
from .schemas import (
    SignupIn, LoginIn, TokenOut, UserOut,
    TenantIn, TenantOut,
    AgentIn, AgentPatch, AgentOut, AgentTestOut,
    ApiKeyIn, ApiKeyOut,
    MemoryIn, MemoryOut, MemoryPatch,
    IngestIn, IngestOut,
    SearchIn, SearchOut, SearchHit,
    TraceOut,
    StatsOut,
    ConsolidateIn, ConsolidateOut, ConsolidatePair,
    GraphOut, GraphEntityOut, GraphRelationOut,
    PlanOut, SubscribeIn, SubscribeOut, BillingStatusOut,
    ContactIn, ContactOut, AdminUserRow, AdminUserUpdate,
)
from .auth import new_api_key, require_key, resolve_agent_for_write, KeyContext, tenant_from_any_auth
from .auth_user import (
    hash_password, verify_password, issue_jwt, current_user,
    encrypt_secret,
)
from .embeddings import embed_for_agent
from .rerank import rerank as rerank_call, RerankUnavailable
from .llm import rewrite_query
from .extract import extract_memories
from .consolidate import consolidate as run_consolidate
from .reconcile import reconcile_write
from .graph import ingest_to_graph, graph_candidates
from . import billing
from .config import settings


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Mneme", version="0.2.0", description="Memory-as-a-Service for LLM agents")

_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- admin (operator) helpers ----

def _is_admin(user) -> bool:
    admins = {e.strip().lower() for e in (settings.admin_emails or "").split(",") if e.strip()}
    return bool(user) and user.email.lower() in admins


def _user_out(user) -> UserOut:
    out = UserOut.model_validate(user)
    out.is_admin = _is_admin(user)
    return out


def require_admin(ctx: Tuple[User, Tenant] = Depends(current_user)) -> Tuple[User, Tenant]:
    """current_user + operator-email gate. 403 for non-admins."""
    if not _is_admin(ctx[0]):
        raise HTTPException(403, "admin only")
    return ctx


@app.get("/health")
def health():
    return {"ok": True, "version": "0.2.0"}


@app.post("/v1/contact")
def contact(body: ContactIn, db: Session = Depends(get_db)):
    """Public 'Contact us' submission from the landing page (no auth)."""
    db.add(ContactMessage(name=body.name.strip(), email=str(body.email), message=body.message.strip()))
    db.commit()
    return {"ok": True}


@app.get("/v1/admin/contact", response_model=List[ContactOut])
def list_contact(ctx: Tuple[User, Tenant] = Depends(require_admin), db: Session = Depends(get_db)):
    """List landing-page contact submissions (most recent first). Operator-only."""
    return db.query(ContactMessage).order_by(desc(ContactMessage.created_at)).limit(500).all()


@app.get("/v1/admin/users", response_model=List[AdminUserRow])
def admin_list_users(ctx: Tuple[User, Tenant] = Depends(require_admin), db: Session = Depends(get_db)):
    """All users with their workspace, plan, subscription status, and account state."""
    users = db.query(User).order_by(desc(User.created_at)).limit(1000).all()
    tenants = {t.owner_user_id: t for t in db.query(Tenant).all()}
    rows: List[AdminUserRow] = []
    for u in users:
        t = tenants.get(u.id)
        agent_count = mem_count = 0
        if t:
            agent_count = db.query(func.count(Agent.id)).filter(Agent.tenant_id == t.id).scalar() or 0
            mem_count = db.query(func.count(Memory.id)).filter(Memory.tenant_id == t.id).scalar() or 0
        rows.append(AdminUserRow(
            id=u.id, email=u.email, name=u.name, disabled=bool(u.disabled),
            is_admin=_is_admin(u), created_at=u.created_at,
            tenant_id=t.id if t else None, tenant_name=t.name if t else None,
            plan=(t.plan if t else "free") or "free",
            subscription_status=(t.subscription_status if t else None),
            agent_count=int(agent_count), memory_count=int(mem_count),
        ))
    return rows


@app.post("/v1/admin/users/{user_id}", response_model=AdminUserRow)
def admin_set_user(user_id: UUID, body: AdminUserUpdate,
                   ctx: Tuple[User, Tenant] = Depends(require_admin), db: Session = Depends(get_db)):
    """Enable/disable an account. Disabling blocks login and invalidates active tokens."""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "user not found")
    if body.disabled and _is_admin(u):
        raise HTTPException(400, "cannot disable an admin account")
    u.disabled = body.disabled
    db.commit()
    db.refresh(u)
    t = db.query(Tenant).filter(Tenant.owner_user_id == u.id).first()
    return AdminUserRow(
        id=u.id, email=u.email, name=u.name, disabled=bool(u.disabled), is_admin=_is_admin(u),
        created_at=u.created_at, tenant_id=t.id if t else None, tenant_name=t.name if t else None,
        plan=(t.plan if t else "free") or "free",
        subscription_status=(t.subscription_status if t else None),
    )


# ==========================================================================
# Auth
# ==========================================================================

@app.post("/v1/auth/signup", response_model=TokenOut)
def signup(body: SignupIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(400, "email already registered")

    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        name=body.name,
    )
    db.add(user)
    db.flush()

    tname = body.tenant_name or (f"{body.name}'s workspace" if body.name else f"{body.email.split('@')[0]} workspace")
    tenant = Tenant(name=tname, owner_user_id=user.id, embedding_dim=settings.embedding_dim)
    db.add(tenant)
    db.commit()
    db.refresh(user)
    db.refresh(tenant)

    token = issue_jwt(user.id, tenant.id)
    return TokenOut(
        access_token=token,
        user=_user_out(user),
        tenant=TenantOut.model_validate(tenant),
    )


@app.post("/v1/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "invalid credentials")
    if user.disabled:
        raise HTTPException(403, "account disabled — contact the operator")
    tenant = db.query(Tenant).filter(Tenant.owner_user_id == user.id).first()
    if not tenant:
        # bare user without tenant (shouldn't happen after signup); create on demand
        tenant = Tenant(name=f"{user.email.split('@')[0]} workspace", owner_user_id=user.id, embedding_dim=settings.embedding_dim)
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
    token = issue_jwt(user.id, tenant.id)
    return TokenOut(
        access_token=token,
        user=_user_out(user),
        tenant=TenantOut.model_validate(tenant),
    )


@app.get("/v1/auth/me", response_model=TokenOut)
def me(ctx: Tuple[User, Tenant] = Depends(current_user)):
    user, tenant = ctx
    # Re-issue a fresh token for client convenience (optional)
    token = issue_jwt(user.id, tenant.id)
    return TokenOut(
        access_token=token,
        user=_user_out(user),
        tenant=TenantOut.model_validate(tenant),
    )


# ==========================================================================
# Plan-limit enforcement
# ==========================================================================

def _enforce_quota(db: Session, tenant: Tenant, resource: str, model, adding: int = 1) -> None:
    """Reject a write that would push `tenant` past its plan cap for `resource`.

    `model` is the per-tenant ORM class to count (Agent or Memory). A plan with no
    cap for the resource is unlimited. Raises HTTP 402 when the cap would be exceeded.
    """
    cap = billing.limits_for(tenant.plan).get(resource)
    if cap is None:
        return
    current = db.query(func.count(model.id)).filter(model.tenant_id == tenant.id).scalar() or 0
    if current + adding > cap:
        raise HTTPException(
            402,
            f"{resource} limit reached for the '{tenant.plan or 'free'}' plan "
            f"({current}/{cap}). Upgrade your plan to add more.",
        )


# ==========================================================================
# Agents (user-authed)
# ==========================================================================

def _agent_to_out(a: Agent, mem_count: int = 0) -> AgentOut:
    return AgentOut(
        id=a.id,
        tenant_id=a.tenant_id,
        slug=a.slug,
        name=a.name,
        description=a.description,
        llm_provider=a.llm_provider,
        llm_model=a.llm_model,
        llm_api_key_set=bool(a.llm_api_key_enc),
        llm_base_url=a.llm_base_url,
        aws_region=a.aws_region,
        aws_access_key_set=bool(a.aws_access_key_enc),
        aws_secret_key_set=bool(a.aws_secret_key_enc),
        embedding_provider=a.embedding_provider,
        embedding_model=a.embedding_model,
        embedding_api_key_set=bool(a.embedding_api_key_enc),
        embedding_base_url=a.embedding_base_url,
        rerank_provider=a.rerank_provider or "none",
        rerank_model=a.rerank_model or "rerank-english-v3.0",
        rerank_api_key_set=bool(a.rerank_api_key_enc),
        auto_extract=a.auto_extract,
        reconcile=bool(a.reconcile),
        graph_enabled=bool(a.graph_enabled),
        memory_count=mem_count,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


@app.post("/v1/agents", response_model=AgentOut)
def create_agent(body: AgentIn, ctx: Tuple[User, Tenant] = Depends(current_user), db: Session = Depends(get_db)):
    _, tenant = ctx
    slug = (body.slug or slugify(body.name))[:80]
    if not slug:
        raise HTTPException(400, "could not derive slug from name")

    if db.query(Agent).filter(Agent.tenant_id == tenant.id, Agent.slug == slug).first():
        raise HTTPException(409, f"agent with slug '{slug}' already exists")

    _enforce_quota(db, tenant, "agents", Agent)

    agent = Agent(
        tenant_id=tenant.id,
        slug=slug,
        name=body.name,
        description=body.description,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        llm_api_key_enc=encrypt_secret(body.llm_api_key),
        llm_base_url=body.llm_base_url or None,
        aws_region=body.aws_region or None,
        aws_access_key_enc=encrypt_secret(body.aws_access_key),
        aws_secret_key_enc=encrypt_secret(body.aws_secret_key),
        embedding_provider=body.embedding_provider,
        embedding_model=body.embedding_model,
        embedding_api_key_enc=encrypt_secret(body.embedding_api_key),
        embedding_base_url=body.embedding_base_url or None,
        rerank_provider=body.rerank_provider,
        rerank_model=body.rerank_model,
        rerank_api_key_enc=encrypt_secret(body.rerank_api_key),
        auto_extract=body.auto_extract,
        reconcile=body.reconcile,
        graph_enabled=body.graph_enabled,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return _agent_to_out(agent, 0)


@app.get("/v1/agents", response_model=List[AgentOut])
def list_agents(ctx: Tuple[User, Tenant] = Depends(current_user), db: Session = Depends(get_db)):
    _, tenant = ctx
    agents = db.query(Agent).filter(Agent.tenant_id == tenant.id).order_by(desc(Agent.created_at)).all()
    counts = dict(
        db.query(Memory.agent_id, func.count(Memory.id))
        .filter(Memory.tenant_id == tenant.id)
        .group_by(Memory.agent_id)
        .all()
    )
    return [_agent_to_out(a, counts.get(a.slug, 0)) for a in agents]


@app.get("/v1/agents/{slug}", response_model=AgentOut)
def get_agent(slug: str, ctx: Tuple[User, Tenant] = Depends(current_user), db: Session = Depends(get_db)):
    _, tenant = ctx
    a = db.query(Agent).filter(Agent.tenant_id == tenant.id, Agent.slug == slug).first()
    if not a:
        raise HTTPException(404, "agent not found")
    mc = db.query(func.count(Memory.id)).filter(Memory.tenant_id == tenant.id, Memory.agent_id == slug).scalar() or 0
    return _agent_to_out(a, int(mc))


@app.patch("/v1/agents/{slug}", response_model=AgentOut)
def update_agent(slug: str, body: AgentPatch, ctx: Tuple[User, Tenant] = Depends(current_user), db: Session = Depends(get_db)):
    _, tenant = ctx
    a = db.query(Agent).filter(Agent.tenant_id == tenant.id, Agent.slug == slug).first()
    if not a:
        raise HTTPException(404, "agent not found")
    for field in ("name", "description", "llm_provider", "llm_model", "llm_base_url", "aws_region",
                  "embedding_provider", "embedding_model", "embedding_base_url",
                  "rerank_provider", "rerank_model", "auto_extract", "reconcile", "graph_enabled"):
        v = getattr(body, field)
        if v is not None:
            setattr(a, field, v if v != "" else None)
    if body.llm_api_key is not None:
        a.llm_api_key_enc = encrypt_secret(body.llm_api_key) if body.llm_api_key else None
    if body.aws_access_key is not None:
        a.aws_access_key_enc = encrypt_secret(body.aws_access_key) if body.aws_access_key else None
    if body.aws_secret_key is not None:
        a.aws_secret_key_enc = encrypt_secret(body.aws_secret_key) if body.aws_secret_key else None
    if body.embedding_api_key is not None:
        a.embedding_api_key_enc = encrypt_secret(body.embedding_api_key) if body.embedding_api_key else None
    if body.rerank_api_key is not None:
        a.rerank_api_key_enc = encrypt_secret(body.rerank_api_key) if body.rerank_api_key else None
    db.commit()
    db.refresh(a)
    return _agent_to_out(a)


@app.post("/v1/agents/{slug}/reembed")
def reembed_agent(slug: str, ctx: Tuple[User, Tenant] = Depends(current_user), db: Session = Depends(get_db)):
    """Recompute embeddings for all of this agent's memories using its CURRENT
    embedding config. Run this after changing an agent's embedding provider/model
    so old vectors don't mismatch the new ones at query time."""
    _, tenant = ctx
    agent = db.query(Agent).filter(Agent.tenant_id == tenant.id, Agent.slug == slug).first()
    if not agent:
        raise HTTPException(404, "agent not found")

    from .embeddings import embed_for_agent
    mems = db.query(Memory).filter(Memory.tenant_id == tenant.id, Memory.agent_id == slug).all()
    updated, errors = 0, 0
    for m in mems:
        try:
            m.embedding = embed_for_agent(m.content, agent, tenant.embedding_dim)
            updated += 1
        except Exception:
            errors += 1
    db.commit()
    return {"agent": slug, "total": len(mems), "reembedded": updated, "errors": errors,
            "provider": agent.embedding_provider, "model": agent.embedding_model}


@app.post("/v1/agents/{slug}/test", response_model=AgentTestOut)
def test_agent(slug: str, ctx: Tuple[User, Tenant] = Depends(current_user), db: Session = Depends(get_db)):
    """Probe the agent's embedding + LLM config. Useful for verifying Ollama
    connectivity (local or remote) and that API keys / base URLs work."""
    _, tenant = ctx
    a = db.query(Agent).filter(Agent.tenant_id == tenant.id, Agent.slug == slug).first()
    if not a:
        raise HTTPException(404, "agent not found")

    out = AgentTestOut(embedding_ok=False, llm_ok=False)

    try:
        from .embeddings import embed_for_agent
        vec = embed_for_agent("ping", a, tenant.embedding_dim)
        out.embedding_ok = True
        out.embedding_dim = len(vec)
    except Exception as e:
        out.embedding_error = str(e)

    if a.llm_provider == "none":
        out.llm_ok = True  # explicit "no LLM" — counts as ok
        out.llm_sample = "(none — no LLM configured)"
    else:
        try:
            from .llm import chat
            reply = chat(a, [{"role": "user", "content": "Say 'pong' in one word."}], max_tokens=12)
            out.llm_ok = True
            out.llm_sample = reply.strip()[:120]
        except Exception as e:
            out.llm_error = str(e)

    return out


@app.delete("/v1/agents/{slug}")
def delete_agent(slug: str, ctx: Tuple[User, Tenant] = Depends(current_user), db: Session = Depends(get_db)):
    _, tenant = ctx
    a = db.query(Agent).filter(Agent.tenant_id == tenant.id, Agent.slug == slug).first()
    if not a:
        raise HTTPException(404, "agent not found")

    # Delete the agent's PRIVATE memories: once the agent is gone they're unreachable
    # (search is scoped to own-agent + shared) yet would keep consuming the plan's memory
    # quota. SHARED memories are KEPT — other agents in the tenant still read them, and
    # agent_id is retained purely as provenance for who wrote them.
    deleted_private = (
        db.query(Memory)
        .filter(Memory.tenant_id == tenant.id, Memory.agent_id == slug, Memory.scope == "private")
        .delete(synchronize_session=False)
    )
    kept_shared = (
        db.query(func.count(Memory.id))
        .filter(Memory.tenant_id == tenant.id, Memory.agent_id == slug, Memory.scope == "shared")
        .scalar() or 0
    )
    # Drop the agent's knowledge graph (built per-agent). Relations before entities so the
    # count is exact and we don't depend on the FK cascade.
    deleted_relations = (
        db.query(GraphRelation)
        .filter(GraphRelation.tenant_id == tenant.id, GraphRelation.agent_id == slug)
        .delete(synchronize_session=False)
    )
    deleted_entities = (
        db.query(GraphEntity)
        .filter(GraphEntity.tenant_id == tenant.id, GraphEntity.agent_id == slug)
        .delete(synchronize_session=False)
    )

    db.delete(a)
    db.commit()
    return {
        "ok": True,
        "deleted_private_memories": int(deleted_private),
        "kept_shared_memories": int(kept_shared),
        "deleted_graph_entities": int(deleted_entities),
        "deleted_graph_relations": int(deleted_relations),
    }


# ==========================================================================
# API keys (user-authed)
# ==========================================================================

@app.post("/v1/keys", response_model=ApiKeyOut)
def create_key(body: ApiKeyIn, ctx: Tuple[User, Tenant] = Depends(current_user), db: Session = Depends(get_db)):
    _, tenant = ctx
    if body.agent_slug:
        a = db.query(Agent).filter(Agent.tenant_id == tenant.id, Agent.slug == body.agent_slug).first()
        if not a:
            raise HTTPException(404, f"agent '{body.agent_slug}' not found")
    k = ApiKey(tenant_id=tenant.id, agent_slug=body.agent_slug, key=new_api_key(), label=body.label or "default")
    db.add(k)
    db.commit()
    db.refresh(k)
    return k


@app.get("/v1/keys", response_model=List[ApiKeyOut])
def list_keys(
    ctx: Tuple[User, Tenant] = Depends(current_user),
    db: Session = Depends(get_db),
    agent_slug: Optional[str] = None,
):
    _, tenant = ctx
    q = db.query(ApiKey).filter(ApiKey.tenant_id == tenant.id)
    if agent_slug:
        q = q.filter(ApiKey.agent_slug == agent_slug)
    return q.order_by(desc(ApiKey.created_at)).all()


@app.delete("/v1/keys/{key_id}")
def delete_key(key_id: UUID, ctx: Tuple[User, Tenant] = Depends(current_user), db: Session = Depends(get_db)):
    _, tenant = ctx
    k = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.tenant_id == tenant.id).first()
    if not k:
        raise HTTPException(404, "key not found")
    db.delete(k)
    db.commit()
    return {"ok": True}


# ==========================================================================
# Memories (api-key authed)
# ==========================================================================

@app.post("/v1/memories", response_model=MemoryOut)
def add_memory(body: MemoryIn, ctx: KeyContext = Depends(require_key), db: Session = Depends(get_db)):
    t0 = time.perf_counter()
    _enforce_quota(db, ctx.tenant, "memories", Memory)
    agent = resolve_agent_for_write(ctx, body.agent_id, db)
    effective_agent_slug = agent.slug if agent else body.agent_id

    operation = "ADD"
    if agent and agent.reconcile:
        # Mem0-style: LLM decides ADD/UPDATE/DELETE/NOOP against near-duplicates.
        m, operation = reconcile_write(
            db, ctx.tenant, agent,
            content=body.content, kind=body.kind, scope=body.scope,
            user_id=body.user_id, session_id=body.session_id,
            importance=body.importance, meta=body.meta or {},
        )
    else:
        vec = embed_for_agent(body.content, agent, ctx.tenant.embedding_dim)
        m = Memory(
            tenant_id=ctx.tenant.id, agent_id=effective_agent_slug,
            user_id=body.user_id, session_id=body.session_id,
            content=body.content, kind=body.kind, scope=body.scope,
            meta=body.meta or {}, importance=body.importance, embedding=vec,
        )
        db.add(m)

    db.commit()
    db.refresh(m)

    db.add(Trace(
        tenant_id=ctx.tenant.id,
        agent_id=effective_agent_slug,
        user_id=body.user_id,
        session_id=body.session_id,
        op="add",
        query=None,
        results={"memory_id": str(m.id), "operation": operation, "content_preview": m.content[:120]},
        latency_ms=int((time.perf_counter() - t0) * 1000),
    ))
    db.commit()

    _maybe_graph(db, ctx.tenant, agent, m, operation)

    out = MemoryOut.model_validate(m)
    out.operation = operation
    return out


def _maybe_graph(db: Session, tenant: Tenant, agent: Optional[Agent], m: Memory, operation: str = "ADD"):
    """Best-effort graph extraction for a written memory. Never breaks the write."""
    if not agent or not agent.graph_enabled or operation == "NOOP":
        return
    try:
        ingest_to_graph(db, tenant, agent, m.content, source_memory_id=m.id)
        db.commit()
    except Exception:
        db.rollback()


@app.post("/v1/memories/ingest", response_model=IngestOut)
def ingest(body: IngestIn, ctx: KeyContext = Depends(require_key), db: Session = Depends(get_db)):
    """Auto-extract atomic memories from a conversation. Uses the agent's LLM
    to find facts worth remembering, then embeds + writes each one."""
    t0 = time.perf_counter()
    agent = resolve_agent_for_write(ctx, body.agent_id, db)
    if not agent:
        raise HTTPException(400, "ingest requires an agent (either via agent-scoped key or agent_id in body)")
    if (agent.llm_provider or "none") == "none":
        raise HTTPException(400, f"agent '{agent.slug}' has no LLM configured — set one to use /ingest")

    # Plan-limit: reject up front if there's no room for even one memory; otherwise
    # cap how many of the extracted facts we persist this batch.
    mem_cap = billing.limits_for(ctx.tenant.plan).get("memories")
    remaining: Optional[int] = None
    if mem_cap is not None and body.persist:
        current = db.query(func.count(Memory.id)).filter(Memory.tenant_id == ctx.tenant.id).scalar() or 0
        if current >= mem_cap:
            raise HTTPException(
                402,
                f"memories limit reached for the '{ctx.tenant.plan or 'free'}' plan "
                f"({current}/{mem_cap}). Upgrade your plan to add more.",
            )
        remaining = mem_cap - current

    messages = [m.model_dump() for m in (body.messages or [])] or None

    try:
        extracted, raw = extract_memories(agent, messages, body.text, body.context)
    except Exception as ex:
        raise HTTPException(502, f"extraction failed: {ex}")

    persisted: List[Memory] = []
    ops_summary: dict = {}
    out_memories: List[MemoryOut] = []
    skipped_for_limit = 0
    if body.persist:
        for item in extracted:
            if remaining is not None and remaining <= 0:
                skipped_for_limit += 1
                continue
            if agent.reconcile:
                m, op = reconcile_write(
                    db, ctx.tenant, agent,
                    content=item["content"], kind=item["kind"], scope=body.scope,
                    user_id=body.user_id, session_id=body.session_id,
                    importance=body.importance, meta={"source": "ingest"},
                )
            else:
                vec = embed_for_agent(item["content"], agent, ctx.tenant.embedding_dim)
                m = Memory(
                    tenant_id=ctx.tenant.id, agent_id=agent.slug,
                    user_id=body.user_id, session_id=body.session_id,
                    content=item["content"], kind=item["kind"], scope=body.scope,
                    meta={"source": "ingest"}, importance=body.importance, embedding=vec,
                )
                db.add(m)
                op = "ADD"
            ops_summary[op] = ops_summary.get(op, 0) + 1
            if op in ("ADD", "DELETE") and remaining is not None:
                remaining -= 1  # only row-creating ops consume quota
            if op != "NOOP":
                persisted.append(m)
        db.commit()
        for m in persisted:
            db.refresh(m)
            mo = MemoryOut.model_validate(m)
            out_memories.append(mo)
        if agent.graph_enabled:
            for m in persisted:
                _maybe_graph(db, ctx.tenant, agent, m)

    latency_ms = int((time.perf_counter() - t0) * 1000)

    trace = Trace(
        tenant_id=ctx.tenant.id,
        agent_id=agent.slug,
        user_id=body.user_id,
        session_id=body.session_id,
        op="ingest",
        query=None,
        results={
            "extracted": len(extracted),
            "persisted": len(persisted),
            "skipped_for_limit": skipped_for_limit,
            "operations": ops_summary,
            "items": [{"content": e["content"][:160], "kind": e["kind"]} for e in extracted],
            "persist": body.persist,
            "reconcile": bool(agent.reconcile),
            "input_messages": len(messages or []),
            "input_text_chars": len(body.text or ""),
        },
        latency_ms=latency_ms,
    )
    db.add(trace)
    db.commit()
    db.refresh(trace)

    return IngestOut(
        extracted=len(extracted),
        persisted=len(persisted),
        memories=out_memories,
        operations=ops_summary,
        raw_llm_response=raw,
        trace_id=trace.id,
        latency_ms=latency_ms,
    )


@app.get("/v1/memories", response_model=List[MemoryOut])
def list_memories(
    ctx: KeyContext = Depends(require_key),
    db: Session = Depends(get_db),
    agent_id: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    q = db.query(Memory).filter(
        Memory.tenant_id == ctx.tenant.id,
        Memory.superseded_by_id.is_(None),
    )
    effective_agent = ctx.bound_agent_slug or agent_id
    if effective_agent:
        # own + shared pool (same model as search)
        q = q.filter(or_(Memory.agent_id == effective_agent, Memory.scope == "shared"))
    if user_id:
        q = q.filter(Memory.user_id == user_id)
    if session_id:
        q = q.filter(Memory.session_id == session_id)
    if kind:
        q = q.filter(Memory.kind == kind)
    return q.order_by(desc(Memory.created_at)).offset(offset).limit(limit).all()


@app.get("/v1/memories/{memory_id}", response_model=MemoryOut)
def get_memory(memory_id: UUID, ctx: KeyContext = Depends(require_key), db: Session = Depends(get_db)):
    m = db.query(Memory).filter(Memory.id == memory_id, Memory.tenant_id == ctx.tenant.id).first()
    if not m:
        raise HTTPException(404, "not found")
    if ctx.bound_agent_slug and m.agent_id != ctx.bound_agent_slug:
        raise HTTPException(403, "memory belongs to a different agent")
    return m


@app.patch("/v1/memories/{memory_id}", response_model=MemoryOut)
def update_memory(memory_id: UUID, body: MemoryPatch, ctx: KeyContext = Depends(require_key), db: Session = Depends(get_db)):
    m = db.query(Memory).filter(Memory.id == memory_id, Memory.tenant_id == ctx.tenant.id).first()
    if not m:
        raise HTTPException(404, "not found")
    if ctx.bound_agent_slug and m.agent_id != ctx.bound_agent_slug:
        raise HTTPException(403, "memory belongs to a different agent")
    if body.content is not None:
        m.content = body.content
        agent = db.query(Agent).filter(Agent.tenant_id == ctx.tenant.id, Agent.slug == m.agent_id).first() if m.agent_id else None
        m.embedding = embed_for_agent(body.content, agent, ctx.tenant.embedding_dim)
    if body.meta is not None:
        m.meta = body.meta
    if body.importance is not None:
        m.importance = body.importance
    db.commit()
    db.refresh(m)
    return m


@app.delete("/v1/memories/{memory_id}")
def delete_memory(memory_id: UUID, ctx: KeyContext = Depends(require_key), db: Session = Depends(get_db)):
    m = db.query(Memory).filter(Memory.id == memory_id, Memory.tenant_id == ctx.tenant.id).first()
    if not m:
        raise HTTPException(404, "not found")
    if ctx.bound_agent_slug and m.agent_id != ctx.bound_agent_slug:
        raise HTTPException(403, "memory belongs to a different agent")
    db.delete(m)
    db.commit()
    return {"ok": True}


# -------- Graph memory --------

@app.get("/v1/graph", response_model=GraphOut)
def get_graph(
    ctx: KeyContext = Depends(require_key),
    db: Session = Depends(get_db),
    agent_id: Optional[str] = None,
    limit: int = Query(300, le=2000),
):
    """Return entities + relations for visualization, scoped to the key's agent
    (or `agent_id` for tenant-wide keys; omit for the whole tenant)."""
    effective_agent = ctx.bound_agent_slug or agent_id
    eq = db.query(GraphEntity).filter(GraphEntity.tenant_id == ctx.tenant.id)
    rq = db.query(GraphRelation).filter(GraphRelation.tenant_id == ctx.tenant.id)
    if effective_agent:
        eq = eq.filter(GraphEntity.agent_id == effective_agent)
        rq = rq.filter(GraphRelation.agent_id == effective_agent)
    entities = eq.order_by(desc(GraphEntity.mention_count)).limit(limit).all()
    relations = rq.limit(limit * 3).all()
    return GraphOut(
        entities=[GraphEntityOut.model_validate(e) for e in entities],
        relations=[GraphRelationOut.model_validate(r) for r in relations],
    )


@app.post("/v1/graph/rebuild")
def rebuild_graph(
    ctx: KeyContext = Depends(require_key),
    db: Session = Depends(get_db),
    agent_id: Optional[str] = None,
):
    """(Re)build the graph from the agent's existing memories. Useful after enabling
    graph memory on an agent that already has memories. Requires the agent to have an LLM."""
    slug = ctx.bound_agent_slug or agent_id
    if not slug:
        raise HTTPException(400, "agent required (agent-scoped key or agent_id)")
    agent = db.query(Agent).filter(Agent.tenant_id == ctx.tenant.id, Agent.slug == slug).first()
    if not agent:
        raise HTTPException(404, "agent not found")
    if (agent.llm_provider or "none") == "none":
        raise HTTPException(400, "agent has no LLM configured")

    mems = db.query(Memory).filter(
        Memory.tenant_id == ctx.tenant.id, Memory.agent_id == slug,
        Memory.superseded_by_id.is_(None),
    ).all()
    ents, rels, errs = 0, 0, 0
    for m in mems:
        try:
            e, r = ingest_to_graph(db, ctx.tenant, agent, m.content, source_memory_id=m.id)
            ents += e
            rels += r
            db.commit()
        except Exception:
            db.rollback()
            errs += 1
    return {"agent": slug, "memories_processed": len(mems),
            "entities_touched": ents, "relations_added": rels, "errors": errs}


# -------- Search --------

def _recency_boost(created_at: datetime, half_life_hours: float = 168.0) -> float:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600.0
    return math.pow(0.5, age_hours / half_life_hours)


def _apply_scope_filters(stmt, ctx: KeyContext, body: SearchIn):
    """Shared-pool scoping for search.

    - Always tenant-isolated; superseded memories excluded.
    - When an agent is resolved: returns that agent's OWN memories + the SHARED pool
      (scope='shared' from any agent in the tenant).
    - cross_agent (see every agent's private memories too) is honored ONLY for
      tenant-wide keys. Agent-scoped keys can never escape own+shared.
    """
    stmt = stmt.where(Memory.tenant_id == ctx.tenant.id, Memory.superseded_by_id.is_(None))

    is_agent_scoped = ctx.bound_agent_slug is not None
    allow_cross = bool(body.cross_agent) and not is_agent_scoped
    effective_agent = ctx.bound_agent_slug or body.agent_id

    if effective_agent and not allow_cross:
        stmt = stmt.where(
            or_(Memory.agent_id == effective_agent, Memory.scope == "shared")
        )
    # else (tenant-wide key with no agent, or allow_cross): no per-agent restriction.

    if body.user_id:
        stmt = stmt.where(Memory.user_id == body.user_id)
    if body.session_id:
        stmt = stmt.where(Memory.session_id == body.session_id)
    if body.kind:
        stmt = stmt.where(Memory.kind == body.kind)
    return stmt


@app.post("/v1/memories/search", response_model=SearchOut)
def search_memories(body: SearchIn, ctx: KeyContext = Depends(require_key), db: Session = Depends(get_db)):
    t0 = time.perf_counter()

    # Resolve agent (for embedding/LLM/rerank config) -- vector mode and hybrid need it.
    slug_for_embed = ctx.bound_agent_slug or body.agent_id
    agent = None
    if slug_for_embed:
        agent = db.query(Agent).filter(
            Agent.tenant_id == ctx.tenant.id, Agent.slug == slug_for_embed
        ).first()

    candidates = max(body.candidates, body.limit)
    effective_agent = ctx.bound_agent_slug or body.agent_id

    # -------- Optional query rewriting --------
    original_query = body.query
    used_query = body.query
    rewritten_query: Optional[str] = None
    rewrite_error: Optional[str] = None
    if body.rewrite:
        try:
            rewritten_query = rewrite_query(agent, body.query)
            if rewritten_query:
                used_query = rewritten_query
        except Exception as ex:
            rewrite_error = str(ex)

    # -------- Vector leg --------
    vector_results: List[Tuple[Memory, float]] = []
    if body.mode in ("vector", "hybrid"):
        q_vec = embed_for_agent(used_query, agent, ctx.tenant.embedding_dim)
        v_stmt = select(
            Memory,
            (1 - Memory.embedding.cosine_distance(q_vec)).label("sim"),
        )
        v_stmt = _apply_scope_filters(v_stmt, ctx, body)
        v_stmt = v_stmt.order_by(Memory.embedding.cosine_distance(q_vec)).limit(candidates)
        vector_results = [(row[0], float(row[1])) for row in db.execute(v_stmt).all()]

    # -------- Lexical leg (tsvector + ts_rank_cd, BM25-style) --------
    lexical_results: List[Tuple[Memory, float]] = []
    if body.mode in ("lexical", "hybrid") and used_query.strip():
        ts_query = func.websearch_to_tsquery("english", used_query)
        rank_expr = func.ts_rank_cd(Memory.content_tsv, ts_query)
        l_stmt = select(Memory, rank_expr.label("rk"))
        l_stmt = _apply_scope_filters(l_stmt, ctx, body)
        l_stmt = l_stmt.where(Memory.content_tsv.op("@@")(ts_query))
        l_stmt = l_stmt.order_by(desc(rank_expr)).limit(candidates)
        lexical_results = [(row[0], float(row[1])) for row in db.execute(l_stmt).all()]

    # -------- Graph leg (entity-linked, traverses the knowledge graph) --------
    graph_results: List[Tuple[Memory, float]] = []
    if body.use_graph:
        gc = graph_candidates(db, ctx.tenant, effective_agent, used_query, candidates)
        if gc:
            id_to_score = {mid: sc for mid, sc in gc}
            gstmt = select(Memory).where(
                Memory.id.in_(list(id_to_score.keys())),
                Memory.tenant_id == ctx.tenant.id,
                Memory.superseded_by_id.is_(None),
            )
            # respect shared-pool scope for agent-scoped keys
            if ctx.bound_agent_slug:
                gstmt = gstmt.where(
                    or_(Memory.agent_id == ctx.bound_agent_slug, Memory.scope == "shared")
                )
            fetched = db.execute(gstmt).scalars().all()
            # preserve graph score ordering
            fetched.sort(key=lambda m: id_to_score.get(m.id, 0), reverse=True)
            graph_results = [(m, id_to_score.get(m.id, 0.0)) for m in fetched]

    # -------- Reciprocal Rank Fusion --------
    bucket: Dict[UUID, dict] = {}

    def touch(mem: Memory) -> dict:
        entry = bucket.setdefault(mem.id, {
            "memory": mem, "similarity": 0.0, "lexical_score": 0.0, "graph_score": 0.0,
            "vector_rank": None, "lexical_rank": None, "graph_rank": None, "rrf": 0.0,
        })
        return entry

    for rank, (mem, sim) in enumerate(vector_results, start=1):
        e = touch(mem)
        e["similarity"] = sim
        e["vector_rank"] = rank
        e["rrf"] += 1.0 / (body.rrf_k + rank)

    for rank, (mem, lex) in enumerate(lexical_results, start=1):
        e = touch(mem)
        e["lexical_score"] = lex
        e["lexical_rank"] = rank
        e["rrf"] += 1.0 / (body.rrf_k + rank)

    for rank, (mem, gsc) in enumerate(graph_results, start=1):
        e = touch(mem)
        e["graph_score"] = gsc
        e["graph_rank"] = rank
        e["rrf"] += 1.0 / (body.rrf_k + rank)

    # ---- Optional cross-encoder rerank ----
    # Sort candidates by RRF, take top-K, rerank, fold scores into bucket.
    rerank_error: Optional[str] = None
    if body.rerank and bucket:
        ranked = sorted(bucket.values(), key=lambda e: e["rrf"], reverse=True)
        top = ranked[: body.rerank_top_k]
        docs = [e["memory"].content for e in top]
        try:
            rr = rerank_call(agent, used_query, docs)  # [(idx, score), ...]
            for idx, score in rr:
                top[idx]["rerank_score"] = float(score)
        except RerankUnavailable as ex:
            rerank_error = str(ex)
        except Exception as ex:
            rerank_error = f"reranker failed: {ex}"

    # Build hits with recency boost layered on top.
    hits: List[SearchHit] = []
    for e in bucket.values():
        mem = e["memory"]
        boost = _recency_boost(mem.created_at)
        rerank_score = e.get("rerank_score")

        # Base ranking score per mode (overridden by reranker if it produced a score for this hit).
        # When the graph leg is on, vector/lexical single-modes still fuse via RRF so graph counts.
        if rerank_score is not None:
            base = rerank_score
        elif body.mode == "vector" and not body.use_graph:
            base = e["similarity"]
        elif body.mode == "lexical" and not body.use_graph:
            base = e["lexical_score"]
        else:  # hybrid, or any mode with graph augmentation → RRF
            base = e["rrf"]

        final = (1 - body.recency_weight) * base + body.recency_weight * boost

        hits.append(SearchHit(
            memory=MemoryOut.model_validate(mem),
            similarity=e["similarity"],
            lexical_score=e["lexical_score"],
            graph_score=e["graph_score"],
            vector_rank=e["vector_rank"],
            lexical_rank=e["lexical_rank"],
            graph_rank=e["graph_rank"],
            rrf_score=e["rrf"],
            rerank_score=rerank_score,
            recency_boost=boost,
            final_score=final,
        ))

    hits.sort(key=lambda h: h.final_score, reverse=True)
    hits = hits[: body.limit]

    if hits:
        ids = [h.memory.id for h in hits]
        db.query(Memory).filter(Memory.id.in_(ids)).update(
            {Memory.access_count: Memory.access_count + 1, Memory.last_accessed_at: datetime.now(timezone.utc)},
            synchronize_session=False,
        )

    latency_ms = int((time.perf_counter() - t0) * 1000)

    trace_meta = {"mode": body.mode, "rerank": body.rerank, "rewrite": body.rewrite, "use_graph": body.use_graph}
    if body.use_graph:
        trace_meta["graph_hits"] = len(graph_results)
    if rerank_error:
        trace_meta["rerank_error"] = rerank_error
    if rewritten_query:
        trace_meta["rewritten_query"] = rewritten_query
    if rewrite_error:
        trace_meta["rewrite_error"] = rewrite_error

    trace = Trace(
        tenant_id=ctx.tenant.id,
        agent_id=effective_agent,
        user_id=body.user_id,
        session_id=body.session_id,
        op="search",
        query=original_query,
        results={
            "meta": trace_meta,
            "hits": [
                {
                    "memory_id": str(h.memory.id),
                    "content_preview": h.memory.content[:160],
                    "agent_id": h.memory.agent_id,
                    "similarity": round(h.similarity, 4),
                    "lexical_score": round(h.lexical_score, 4),
                    "graph_score": round(h.graph_score, 4),
                    "vector_rank": h.vector_rank,
                    "lexical_rank": h.lexical_rank,
                    "graph_rank": h.graph_rank,
                    "rrf_score": round(h.rrf_score, 5),
                    "rerank_score": round(h.rerank_score, 5) if h.rerank_score is not None else None,
                    "recency_boost": round(h.recency_boost, 4),
                    "final_score": round(h.final_score, 4),
                }
                for h in hits
            ],
        },
        latency_ms=latency_ms,
    )
    db.add(trace)
    db.commit()
    db.refresh(trace)

    return SearchOut(
        trace_id=trace.id,
        hits=hits,
        latency_ms=latency_ms,
        original_query=original_query,
        rewritten_query=rewritten_query,
        rewrite_error=rewrite_error,
    )


# ==========================================================================
# Traces + Stats (both user-authed and api-key authed)
# ==========================================================================

def _tenant_from_either(
    db: Session,
    key_ctx: Optional[KeyContext],
    user_ctx: Optional[Tuple[User, Tenant]],
) -> Tenant:
    if key_ctx:
        return key_ctx.tenant
    if user_ctx:
        return user_ctx[1]
    raise HTTPException(401, "auth required")


@app.get("/v1/traces", response_model=List[TraceOut])
def list_traces(
    tenant: Tenant = Depends(tenant_from_any_auth),
    db: Session = Depends(get_db),
    agent_id: Optional[str] = None,
    op: Optional[str] = None,
    limit: int = Query(100, le=500),
):
    q = db.query(Trace).filter(Trace.tenant_id == tenant.id)
    if agent_id:
        q = q.filter(Trace.agent_id == agent_id)
    if op:
        q = q.filter(Trace.op == op)
    return q.order_by(desc(Trace.created_at)).limit(limit).all()


@app.get("/v1/traces/{trace_id}", response_model=TraceOut)
def get_trace(trace_id: UUID, tenant: Tenant = Depends(tenant_from_any_auth), db: Session = Depends(get_db)):
    t = db.query(Trace).filter(Trace.id == trace_id, Trace.tenant_id == tenant.id).first()
    if not t:
        raise HTTPException(404, "not found")
    return t


@app.get("/v1/stats", response_model=StatsOut)
def stats(tenant: Tenant = Depends(tenant_from_any_auth), db: Session = Depends(get_db)):
    total = db.query(func.count(Memory.id)).filter(Memory.tenant_id == tenant.id).scalar() or 0
    traces = db.query(func.count(Trace.id)).filter(Trace.tenant_id == tenant.id).scalar() or 0
    agents_n = db.query(func.count(Agent.id)).filter(Agent.tenant_id == tenant.id).scalar() or 0

    by_kind = dict(
        db.query(Memory.kind, func.count(Memory.id))
        .filter(Memory.tenant_id == tenant.id)
        .group_by(Memory.kind)
        .all()
    )

    by_agent_rows = (
        db.query(Memory.agent_id, func.count(Memory.id))
        .filter(Memory.tenant_id == tenant.id)
        .group_by(Memory.agent_id)
        .order_by(func.count(Memory.id).desc())
        .limit(10)
        .all()
    )
    by_agent = [{"agent_id": a or "<none>", "count": c} for a, c in by_agent_rows]

    from sqlalchemy import text as _text
    recent_24h = db.execute(
        _text("SELECT count(*) FROM traces WHERE tenant_id = :t AND created_at > now() - interval '24 hours'"),
        {"t": str(tenant.id)},
    ).scalar() or 0

    return StatsOut(
        total_memories=total,
        total_traces=traces,
        total_agents=agents_n,
        memories_by_kind=by_kind,
        memories_by_agent=by_agent,
        recent_ops_24h=int(recent_24h),
        plan=tenant.plan or "free",
        limits=billing.limits_for(tenant.plan),
    )


# ==========================================================================
# Billing (Razorpay)
# ==========================================================================

@app.get("/v1/billing/plans/public", response_model=List[PlanOut])
def billing_plans_public():
    """Public pricing for the landing page (no auth, no per-tenant 'current' flag)."""
    return [
        PlanOut(key=k, name=s["name"], amount=s["amount"], limits=s["limits"], current=False)
        for k, s in billing.PLAN_DEFS.items()
    ]


@app.get("/v1/billing/plans", response_model=List[PlanOut])
def billing_plans(ctx: Tuple[User, Tenant] = Depends(current_user)):
    _, tenant = ctx
    out = []
    for key, spec in billing.PLAN_DEFS.items():
        out.append(PlanOut(
            key=key, name=spec["name"], amount=spec["amount"],
            limits=spec["limits"], current=(tenant.plan == key),
        ))
    return out


@app.get("/v1/billing/status", response_model=BillingStatusOut)
def billing_status(ctx: Tuple[User, Tenant] = Depends(current_user), db: Session = Depends(get_db)):
    _, tenant = ctx
    agents_n = db.query(func.count(Agent.id)).filter(Agent.tenant_id == tenant.id).scalar() or 0
    mems_n = db.query(func.count(Memory.id)).filter(Memory.tenant_id == tenant.id).scalar() or 0
    return BillingStatusOut(
        plan=tenant.plan or "free",
        subscription_status=tenant.subscription_status,
        razorpay_subscription_id=tenant.razorpay_subscription_id,
        configured=bool(settings.razorpay_key_id and settings.razorpay_key_secret),
        usage={"agents": int(agents_n), "memories": int(mems_n)},
        limits=billing.limits_for(tenant.plan),
    )


@app.post("/v1/billing/subscribe", response_model=SubscribeOut)
def billing_subscribe(body: SubscribeIn, ctx: Tuple[User, Tenant] = Depends(current_user), db: Session = Depends(get_db)):
    _, tenant = ctx
    try:
        result = billing.create_subscription(db, tenant, body.plan)
    except billing.BillingNotConfigured as e:
        raise HTTPException(503, f"billing not configured: {e}")
    except Exception as e:
        raise HTTPException(502, f"razorpay error: {e}")
    return SubscribeOut(**result)


@app.post("/v1/billing/webhook")
async def billing_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not billing.verify_webhook(raw, signature):
        raise HTTPException(400, "invalid webhook signature")
    import json as _json
    event = _json.loads(raw.decode("utf-8"))
    etype = billing.apply_webhook_event(db, event)
    return {"ok": True, "event": etype}


# ==========================================================================
# Consolidation (user-authed; tenant-wide maintenance)
# ==========================================================================

@app.post("/v1/admin/consolidate", response_model=ConsolidateOut)
def consolidate_endpoint(
    body: ConsolidateIn,
    ctx: Tuple[User, Tenant] = Depends(current_user),
    db: Session = Depends(get_db),
):
    _, tenant = ctx
    t0 = time.perf_counter()
    result = run_consolidate(
        db,
        tenant,
        similarity_threshold=body.similarity_threshold,
        use_llm_merge=body.use_llm_merge,
        decay_half_life_days=body.decay_half_life_days,
        dry_run=body.dry_run,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    trace = Trace(
        tenant_id=tenant.id,
        op="consolidate",
        query=None,
        results={
            "pairs_found": result["pairs_found"],
            "merges_performed": result["merges_performed"],
            "decayed": result["decayed"],
            "dry_run": body.dry_run,
            "similarity_threshold": body.similarity_threshold,
        },
        latency_ms=latency_ms,
    )
    db.add(trace)
    db.commit()

    pairs = [ConsolidatePair(**d) for d in result["details"]]
    return ConsolidateOut(
        pairs_found=result["pairs_found"],
        merges_performed=result["merges_performed"],
        decayed_count=result["decayed"],
        pairs=pairs,
        latency_ms=latency_ms,
    )
