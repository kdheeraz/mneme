# Mneme — High-Level Design (HLD)

## 1. Purpose & scope

Mneme is a **memory backend for LLM agents**. It is not a RAG framework and not an agent
framework — it sits *below* those. An agent (built with LangChain, CrewAI, raw SDK calls,
etc.) calls Mneme to:

- **write** memories (facts, events, behaviors) it should recall later
- **search** them with hybrid (semantic + lexical) retrieval
- **share** memory across agents in the same workspace
- **maintain** them automatically (extraction, dedup, decay)

Design tenets:
- **The layer your framework calls** — primitives, not opinions.
- **Multi-tenant and multi-agent from day one.**
- **Provider-neutral** — OpenAI, Anthropic, Ollama (local/remote), Cohere/Voyage/Jina.
- **Observable** — every retrieval is explainable via stored traces.

## 2. Actors

| Actor | Auth | What they do |
|-------|------|--------------|
| **User** (human) | JWT (email+password) | Manage workspace, register agents, mint keys, view dashboard |
| **Agent** (machine) | `X-API-Key` | Add / search / ingest memories at runtime |
| **Operator** (you) | shell / Docker | Deploy, run consolidation, observe |

## 3. Core domain model (conceptual)

```
User ──owns──▶ Tenant (workspace) ──has──▶ Agent(s)
                     │                         │
                     ├── ApiKey(s) ────────────┤ (tenant-wide or agent-scoped)
                     │                         │
                     └── Memory(s) ◀──written by/scoped to── Agent
                     └── Trace(s)  (audit of every operation)
```

- A **Tenant** is the hard isolation boundary and owns the embedding dimension.
- An **Agent** is a first-class entity with its own LLM, embedding, and reranker config.
- A **Memory** belongs to a tenant, is attributed to an agent, optionally keyed by
  `user_id` / `session_id`, and is either `private` or `shared`.
- A **Trace** records every `add` / `search` / `ingest` / `consolidate` operation.

## 4. Component architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Mneme API (FastAPI)                          │
│                                                                       │
│  Routing & auth                                                       │
│   ├─ auth_user.py     JWT issue/verify, bcrypt, Fernet secret crypto  │
│   ├─ auth.py          API-key resolution → (tenant, bound agent)      │
│   │                                                                    │
│  Retrieval pipeline                                                    │
│   ├─ embeddings.py    per-agent embed dispatch (fake/openai/ollama)    │
│   ├─ (search)         vector leg + lexical leg → RRF → recency         │
│   ├─ rerank.py        cross-encoder rerank (cohere/voyage/jina)        │
│   ├─ llm.py           chat dispatch; rewrite_query; merge_memories     │
│   │                                                                    │
│  Write / maintenance                                                   │
│   ├─ extract.py       conversation → atomic memories (LLM, JSON mode)  │
│   ├─ consolidate.py   near-dup detection, merge, importance decay      │
│   ├─ jsonutil.py      lenient JSON parsing for small-model output      │
│   │                                                                    │
│  Persistence                                                           │
│   ├─ models.py        SQLAlchemy ORM (pgvector + tsvector)            │
│   ├─ db.py            engine / session                                 │
│   └─ bootstrap.py     wait-for-db, create tables, demo seed            │
└─────────────────────────────────────────────────────────────────────┘
        │                         │                         │
        ▼                         ▼                         ▼
┌────────────────┐      ┌──────────────────┐      ┌────────────────────┐
│ Postgres 16    │      │ Redis            │      │ External providers │
│ + pgvector     │      │ (reserved;       │      │ OpenAI / Anthropic │
│ + tsvector/GIN │      │  cache/queue)    │      │ Ollama / rerankers │
└────────────────┘      └──────────────────┘      └────────────────────┘
```

Plus two clients:
- **Dashboard** (Next.js) — talks to the API with JWT for admin, `X-API-Key` for the
  Memories/Search/Ingest tabs.
- **Python SDK** (`mneme`) — thin `httpx` wrapper over the memory endpoints.

## 5. Request flows

### 5.1 Write a memory
```
SDK ──POST /v1/memories (X-API-Key)──▶ resolve key → (tenant, agent)
   └─ embed content with agent's embedder
   └─ INSERT memory (tenant, agent, scope, vector, tsvector auto)
   └─ INSERT trace(op=add)
```

### 5.2 Search (hybrid + optional rewrite + optional rerank)
```
SDK ──POST /v1/memories/search──▶ resolve key → (tenant, agent)
   ├─ [rewrite?]  LLM expands query (JSON mode)            (llm.py)
   ├─ vector leg: embed(query) → pgvector cosine top-N      (embeddings.py)
   ├─ lexical leg: websearch_to_tsquery → ts_rank_cd top-N
   ├─ RRF fuse the two ranked lists (k=60)
   ├─ [rerank?]   cross-encoder reorders top-K              (rerank.py)
   ├─ recency boost blended into final score
   ├─ scope filter: own + shared (agent) / all (tenant key) 
   └─ INSERT trace(op=search, results=[...]) → return hits + trace_id
```

### 5.3 Auto-extraction (ingest)
```
SDK ──POST /v1/memories/ingest──▶ resolve key → (tenant, agent w/ LLM)
   └─ LLM extracts atomic memories (JSON mode)              (extract.py)
   └─ per memory: embed + INSERT (scope from request)
   └─ INSERT trace(op=ingest)
```

### 5.4 Consolidation (maintenance)
```
Dashboard ──POST /v1/admin/consolidate (JWT)──▶ tenant
   └─ find near-dup pairs via pgvector cosine, scoped (agent,user)  (consolidate.py)
   └─ greedy: pick winner; [LLM merge?] rewrite winner content + re-embed
   └─ mark loser superseded_by_id = winner
   └─ [decay?] importance *= 0.5 ^ (age / half_life)
   └─ INSERT trace(op=consolidate)
```

## 6. Security model

| Boundary | Mechanism |
|----------|-----------|
| Workspace isolation | Every query filtered by `tenant_id`; JWT and API keys both resolve to exactly one tenant |
| Agent isolation | Agent-scoped API key forces `agent_slug`; cannot read other agents' private memories |
| Privilege escalation guard | `cross_agent: true` is honored **only** for tenant-wide keys (agent-scoped keys can't escape own+shared) |
| Secret storage | Third-party API keys (OpenAI/Anthropic/rerank) stored Fernet-encrypted; never returned by the API (only `*_set: bool`) |
| Password storage | bcrypt |
| Transport | Dev: HTTP. Prod: terminate TLS at a proxy (out of scope for the prototype) |

## 7. Deployment topology

Local / single-host via Docker Compose:

```
docker compose
├── db    (pgvector/pgvector:pg16)   :5433→5432   volume: mneme_db
├── redis (redis:7-alpine)           :6380→6379
├── api   (FastAPI/uvicorn --reload) :8000        mounts ./backend
└── web   (Next.js dev)              :3000        mounts ./frontend
```

- `api` reaches local Ollama via `host.docker.internal:11434`
  (`extra_hosts: host.docker.internal:host-gateway` for Linux parity).
- Schema is created on boot via `Base.metadata.create_all` (no migrations yet → schema
  changes require `make reset`, which drops volumes).

Production trajectory (not built):
- Managed Postgres w/ pgvector (or external vector DB)
- Stateless API behind a load balancer; TLS at the edge
- Alembic migrations; secrets in a KMS; Redis for rate-limiting + queues
- Background workers for consolidation (cron/Celery)

## 8. Scaling considerations

| Concern | Now | Next |
|---------|-----|------|
| Vector search | pgvector exact scan (fine < ~100k/tenant) | HNSW/IVFFlat index |
| Lexical search | GIN index on `content_tsv` | partitioning by tenant |
| Embeddings | sync call on write/search | batch + cache; async workers |
| Consolidation | user-triggered, O(pairs) per tenant | scheduled background job |
| Multi-model shared memory | single embedding space per tenant (beta) | per-model vector store (Option A) or Qdrant |

## 9. Observability

- **Traces table** captures every `add`, `search`, `ingest`, `consolidate` with latency,
  inputs, and per-hit scoring (similarity, lexical score, RRF, rerank, recency).
- The dashboard **Traces** tab renders them; **Overview** shows counts and per-agent
  distribution.
- Future: export to OpenTelemetry / Langfuse; per-tenant usage metering for billing.
