import time
import math
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func, desc, literal
from sqlalchemy.orm import Session
from slugify import slugify

from .db import get_db, Base, engine
from .models import User, Tenant, Agent, ApiKey, Memory, Trace
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
)
from .auth import new_api_key, require_key, resolve_agent_for_write, KeyContext
from .auth_user import (
    hash_password, verify_password, issue_jwt, current_user,
    encrypt_secret,
)
from .embeddings import embed_for_agent
from .rerank import rerank as rerank_call, RerankUnavailable
from .llm import rewrite_query
from .extract import extract_memories
from .consolidate import consolidate as run_consolidate
from .config import settings


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Mneme", version="0.2.0", description="Memory-as-a-Service for LLM agents")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True, "version": "0.2.0"}


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
        user=UserOut.model_validate(user),
        tenant=TenantOut.model_validate(tenant),
    )


@app.post("/v1/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "invalid credentials")
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
        user=UserOut.model_validate(user),
        tenant=TenantOut.model_validate(tenant),
    )


@app.get("/v1/auth/me", response_model=TokenOut)
def me(ctx: Tuple[User, Tenant] = Depends(current_user)):
    user, tenant = ctx
    # Re-issue a fresh token for client convenience (optional)
    token = issue_jwt(user.id, tenant.id)
    return TokenOut(
        access_token=token,
        user=UserOut.model_validate(user),
        tenant=TenantOut.model_validate(tenant),
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
        embedding_provider=a.embedding_provider,
        embedding_model=a.embedding_model,
        embedding_api_key_set=bool(a.embedding_api_key_enc),
        embedding_base_url=a.embedding_base_url,
        rerank_provider=a.rerank_provider or "none",
        rerank_model=a.rerank_model or "rerank-english-v3.0",
        rerank_api_key_set=bool(a.rerank_api_key_enc),
        auto_extract=a.auto_extract,
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

    agent = Agent(
        tenant_id=tenant.id,
        slug=slug,
        name=body.name,
        description=body.description,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        llm_api_key_enc=encrypt_secret(body.llm_api_key),
        llm_base_url=body.llm_base_url or None,
        embedding_provider=body.embedding_provider,
        embedding_model=body.embedding_model,
        embedding_api_key_enc=encrypt_secret(body.embedding_api_key),
        embedding_base_url=body.embedding_base_url or None,
        rerank_provider=body.rerank_provider,
        rerank_model=body.rerank_model,
        rerank_api_key_enc=encrypt_secret(body.rerank_api_key),
        auto_extract=body.auto_extract,
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
    for field in ("name", "description", "llm_provider", "llm_model", "llm_base_url",
                  "embedding_provider", "embedding_model", "embedding_base_url",
                  "rerank_provider", "rerank_model", "auto_extract"):
        v = getattr(body, field)
        if v is not None:
            setattr(a, field, v if v != "" else None)
    if body.llm_api_key is not None:
        a.llm_api_key_enc = encrypt_secret(body.llm_api_key) if body.llm_api_key else None
    if body.embedding_api_key is not None:
        a.embedding_api_key_enc = encrypt_secret(body.embedding_api_key) if body.embedding_api_key else None
    if body.rerank_api_key is not None:
        a.rerank_api_key_enc = encrypt_secret(body.rerank_api_key) if body.rerank_api_key else None
    db.commit()
    db.refresh(a)
    return _agent_to_out(a)


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
    db.delete(a)
    db.commit()
    return {"ok": True}


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
    agent = resolve_agent_for_write(ctx, body.agent_id, db)
    effective_agent_slug = agent.slug if agent else body.agent_id

    vec = embed_for_agent(body.content, agent, ctx.tenant.embedding_dim)

    m = Memory(
        tenant_id=ctx.tenant.id,
        agent_id=effective_agent_slug,
        user_id=body.user_id,
        session_id=body.session_id,
        content=body.content,
        kind=body.kind,
        meta=body.meta or {},
        importance=body.importance,
        embedding=vec,
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
        results={"memory_id": str(m.id), "content_preview": body.content[:120]},
        latency_ms=int((time.perf_counter() - t0) * 1000),
    ))
    db.commit()
    return m


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

    messages = [m.model_dump() for m in (body.messages or [])] or None

    try:
        extracted, raw = extract_memories(agent, messages, body.text, body.context)
    except Exception as ex:
        raise HTTPException(502, f"extraction failed: {ex}")

    persisted: List[Memory] = []
    if body.persist:
        for item in extracted:
            vec = embed_for_agent(item["content"], agent, ctx.tenant.embedding_dim)
            m = Memory(
                tenant_id=ctx.tenant.id,
                agent_id=agent.slug,
                user_id=body.user_id,
                session_id=body.session_id,
                content=item["content"],
                kind=item["kind"],
                meta={"source": "ingest"},
                importance=body.importance,
                embedding=vec,
            )
            db.add(m)
            persisted.append(m)
        db.commit()
        for m in persisted:
            db.refresh(m)

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
            "items": [{"content": e["content"][:160], "kind": e["kind"]} for e in extracted],
            "persist": body.persist,
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
        memories=[MemoryOut.model_validate(m) for m in persisted],
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
        q = q.filter(Memory.agent_id == effective_agent)
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


# -------- Search --------

def _recency_boost(created_at: datetime, half_life_hours: float = 168.0) -> float:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600.0
    return math.pow(0.5, age_hours / half_life_hours)


def _apply_scope_filters(stmt, ctx: KeyContext, body: SearchIn):
    """Tenant + agent + user + session + kind filters shared by vector and lexical legs."""
    stmt = stmt.where(Memory.tenant_id == ctx.tenant.id, Memory.superseded_by_id.is_(None))
    effective_agent = ctx.bound_agent_slug or body.agent_id
    if effective_agent and not body.cross_agent:
        stmt = stmt.where(Memory.agent_id == effective_agent)
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

    # -------- Reciprocal Rank Fusion --------
    bucket: Dict[UUID, dict] = {}

    def touch(mem: Memory) -> dict:
        entry = bucket.setdefault(mem.id, {
            "memory": mem, "similarity": 0.0, "lexical_score": 0.0,
            "vector_rank": None, "lexical_rank": None, "rrf": 0.0,
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

        # Base ranking score per mode (overridden by reranker if it produced a score for this hit)
        if rerank_score is not None:
            base = rerank_score
        elif body.mode == "vector":
            base = e["similarity"]
        elif body.mode == "lexical":
            base = e["lexical_score"]
        else:  # hybrid → RRF
            base = e["rrf"]

        final = (1 - body.recency_weight) * base + body.recency_weight * boost

        hits.append(SearchHit(
            memory=MemoryOut.model_validate(mem),
            similarity=e["similarity"],
            lexical_score=e["lexical_score"],
            vector_rank=e["vector_rank"],
            lexical_rank=e["lexical_rank"],
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

    trace_meta = {"mode": body.mode, "rerank": body.rerank, "rewrite": body.rewrite}
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
                    "vector_rank": h.vector_rank,
                    "lexical_rank": h.lexical_rank,
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
    ctx: Tuple[User, Tenant] = Depends(current_user),
    db: Session = Depends(get_db),
    agent_id: Optional[str] = None,
    op: Optional[str] = None,
    limit: int = Query(100, le=500),
):
    _, tenant = ctx
    q = db.query(Trace).filter(Trace.tenant_id == tenant.id)
    if agent_id:
        q = q.filter(Trace.agent_id == agent_id)
    if op:
        q = q.filter(Trace.op == op)
    return q.order_by(desc(Trace.created_at)).limit(limit).all()


@app.get("/v1/traces/{trace_id}", response_model=TraceOut)
def get_trace(trace_id: UUID, ctx: Tuple[User, Tenant] = Depends(current_user), db: Session = Depends(get_db)):
    _, tenant = ctx
    t = db.query(Trace).filter(Trace.id == trace_id, Trace.tenant_id == tenant.id).first()
    if not t:
        raise HTTPException(404, "not found")
    return t


@app.get("/v1/stats", response_model=StatsOut)
def stats(ctx: Tuple[User, Tenant] = Depends(current_user), db: Session = Depends(get_db)):
    _, tenant = ctx
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
    )


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
