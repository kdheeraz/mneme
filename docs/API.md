# Mneme — API Reference (v0.2.0)

Base URL (dev): `http://localhost:8000` · Interactive: `http://localhost:8000/docs`

## Authentication

Two schemes:

| Scheme | Header | Used by | Endpoints |
|--------|--------|---------|-----------|
| **JWT** | `Authorization: Bearer <token>` | dashboard / users | auth, agents, keys, consolidate |
| **API key** | `X-API-Key: mneme_sk_...` | agents / SDK | memories, ingest, search |
| **Either** | JWT *or* API key | both | traces, stats (read-only, tenant-scoped) |

API keys are **tenant-wide** (`agent_slug = null`) or **agent-scoped**. Agent-scoped keys
force their agent and cannot read other agents' private memories.

---

## Health

### `GET /health`
```json
{ "ok": true, "version": "0.2.0" }
```

---

## Auth (JWT)

### `POST /v1/auth/signup`
```json
// request
{ "email": "you@co.com", "password": "min8chars", "name": "You", "tenant_name": "Acme" }
// response
{ "access_token": "<jwt>", "token_type": "bearer",
  "user": { "id": "...", "email": "you@co.com", "name": "You", "created_at": "..." },
  "tenant": { "id": "...", "name": "Acme", "embedding_dim": 768, "plan": "free", "created_at": "..." } }
```
`400` if email already registered.

### `POST /v1/auth/login`
```json
{ "email": "you@co.com", "password": "..." }   // → same shape as signup
```
`401` on bad credentials.

### `GET /v1/auth/me`
Returns a fresh token + user + tenant. Requires `Authorization`.

---

## Agents (JWT)

Agent object:
```json
{
  "id": "uuid", "tenant_id": "uuid", "slug": "research-bot", "name": "Research Bot",
  "description": "...",
  "llm_provider": "ollama", "llm_model": "qwen3:4b", "llm_api_key_set": false, "llm_base_url": "http://host.docker.internal:11434",
  "embedding_provider": "ollama", "embedding_model": "nomic-embed-text", "embedding_api_key_set": false, "embedding_base_url": "http://host.docker.internal:11434",
  "rerank_provider": "none", "rerank_model": "rerank-english-v3.0", "rerank_api_key_set": false,
  "auto_extract": false, "memory_count": 5, "created_at": "...", "updated_at": "..."
}
```
> Secrets are write-only: send `*_api_key`, read back only `*_api_key_set: bool`.

### `POST /v1/agents`
```json
{
  "name": "Research Bot",            // required
  "slug": "research-bot",            // optional; auto-slugified from name
  "description": "...",
  "llm_provider": "none|openai|anthropic|ollama",
  "llm_model": "qwen3:4b",
  "llm_api_key": "sk-...",           // encrypted at rest
  "llm_base_url": "http://host.docker.internal:11434",
  "embedding_provider": "fake|openai|ollama",
  "embedding_model": "nomic-embed-text",
  "embedding_api_key": "sk-...",
  "embedding_base_url": "http://host.docker.internal:11434",
  "rerank_provider": "none|cohere|voyage|jina",
  "rerank_model": "rerank-english-v3.0",
  "rerank_api_key": "...",
  "auto_extract": false
}
```
`409` if slug exists in tenant.

### `GET /v1/agents` → `AgentOut[]` (with `memory_count`)
### `GET /v1/agents/{slug}` → `AgentOut`
### `PATCH /v1/agents/{slug}`
Any subset of the create fields. Sending `""` for a base_url clears it. Sending an empty
`*_api_key` clears the stored secret; omitting it keeps the current one.

### `DELETE /v1/agents/{slug}`
Deletes the agent. **Does not delete its memories** (they keep `agent_id = slug`).

### `POST /v1/agents/{slug}/test`
Probes config. Loads models on first call (can take ~10s).
```json
{ "embedding_ok": true, "embedding_dim": 768, "embedding_error": null,
  "llm_ok": true, "llm_sample": "pong", "llm_error": null }
```
(`llm_ok: true` with empty sample is normal for reasoning models on a tiny budget.)

### `POST /v1/agents/{slug}/reembed`
Recompute **all** of this agent's memory vectors with its current embedding config. Run
after changing the agent's embedding provider/model.
```json
{ "agent": "research-bot", "total": 5, "reembedded": 5, "errors": 0,
  "provider": "ollama", "model": "nomic-embed-text" }
```

---

## API keys (JWT)

Key object:
```json
{ "id": "uuid", "tenant_id": "uuid", "agent_slug": "research-bot|null",
  "key": "mneme_sk_...", "label": "default", "last_used_at": "...", "created_at": "..." }
```

### `POST /v1/keys`
```json
{ "label": "prod", "agent_slug": "research-bot" }   // agent_slug null ⇒ tenant-wide
```
`404` if `agent_slug` doesn't exist.

### `GET /v1/keys?agent_slug=research-bot` → `ApiKeyOut[]`
### `DELETE /v1/keys/{id}` → `{ "ok": true }`

---

## Memories (X-API-Key)

Memory object:
```json
{
  "id": "uuid", "tenant_id": "uuid", "agent_id": "research-bot",
  "user_id": "user_42", "session_id": "sess_1",
  "content": "User prefers PyTorch over TensorFlow",
  "kind": "semantic", "scope": "private", "meta": {}, "importance": 0.5,
  "created_at": "...", "updated_at": "...", "last_accessed_at": "...", "access_count": 0
}
```

### `POST /v1/memories`
```json
{
  "content": "User prefers PyTorch over TensorFlow",   // required
  "agent_id": "research-bot",   // ignored if key is agent-scoped
  "user_id": "user_42",
  "session_id": "sess_1",
  "kind": "semantic|episodic|procedural",
  "scope": "private|shared",
  "meta": { "source": "chat" },
  "importance": 0.5
}
```
`404` if a referenced agent slug isn't registered.

### `POST /v1/memories/ingest`  (auto-extraction; requires agent w/ LLM)
```json
// request — provide messages OR text
{
  "messages": [ { "role": "user", "content": "I like PyTorch. Ship PR notes with a TL;DR." } ],
  "text": null,
  "context": "optional extra context for the extractor",
  "agent_id": "research-bot",
  "user_id": "user_42",
  "session_id": null,
  "scope": "private|shared",
  "persist": true            // false = dry-run, extract but don't write
}
// response
{
  "extracted": 2, "persisted": 2,
  "memories": [ MemoryOut, ... ],
  "raw_llm_response": "{ \"memories\": [...] }",
  "trace_id": "uuid", "latency_ms": 7464
}
```
`400` if no agent / agent has no LLM. `502` if extraction (LLM/parse) fails.

### `GET /v1/memories`
Query params: `agent_id`, `user_id`, `session_id`, `kind`, `limit` (≤500), `offset`.
Returns `own + shared` for an agent context; superseded memories excluded.

### `GET /v1/memories/{id}` → `MemoryOut`
`403` if an agent-scoped key requests another agent's memory.

### `PATCH /v1/memories/{id}`
```json
{ "content": "...", "meta": {...}, "importance": 0.7 }   // content change re-embeds
```

### `DELETE /v1/memories/{id}` → `{ "ok": true }`

### `POST /v1/memories/search`
```json
// request
{
  "query": "what framework does the user prefer?",   // required
  "agent_id": "research-bot",     // ignored if key agent-scoped
  "user_id": "user_42",
  "session_id": null,
  "kind": null,
  "limit": 10,
  "mode": "hybrid|vector|lexical",
  "recency_weight": 0.15,         // 0..1 blend of recency into final score
  "rrf_k": 60,
  "candidates": 30,               // per-leg overfetch before fusion
  "rerank": false,                // cross-encoder rerank (needs reranker on agent)
  "rerank_top_k": 30,
  "rewrite": false,               // LLM query expansion (needs LLM on agent)
  "cross_agent": false            // tenant-wide keys only: read all agents' private too
}
// response
{
  "trace_id": "uuid",
  "latency_ms": 56,
  "original_query": "what framework does the user prefer?",
  "rewritten_query": "framework preference: PyTorch vs TensorFlow ...",   // if rewrite
  "rewrite_error": null,
  "hits": [
    {
      "memory": MemoryOut,
      "similarity": 0.47,        // cosine (0 if not from vector leg)
      "lexical_score": 0.0,      // ts_rank_cd (0 if not from lexical leg)
      "vector_rank": 1,
      "lexical_rank": null,
      "rrf_score": 0.0163,
      "rerank_score": null,      // set when rerank used
      "recency_boost": 0.83,
      "final_score": 0.512
    }
  ]
}
```

---

## Observability (JWT *or* API key)

### `GET /v1/traces?agent_id=&op=&limit=`
`op ∈ {add, search, ingest, consolidate}`. Returns `TraceOut[]`.
```json
{ "id": "uuid", "agent_id": "research-bot", "user_id": "user_42", "session_id": null,
  "op": "search", "query": "...", "results": { "meta": {...}, "hits": [...] },
  "latency_ms": 56, "created_at": "..." }
```

### `GET /v1/traces/{id}` → `TraceOut`

### `GET /v1/stats`
```json
{
  "total_memories": 19, "total_traces": 7, "total_agents": 4,
  "memories_by_kind": { "semantic": 10, "episodic": 4, "procedural": 5 },
  "memories_by_agent": [ { "agent_id": "research-bot", "count": 5 }, ... ],
  "recent_ops_24h": 12
}
```

---

## Consolidation (JWT)

### `POST /v1/admin/consolidate`
```json
// request
{
  "similarity_threshold": 0.92,    // 0..1 cosine
  "use_llm_merge": false,          // LLM-merge winner content (per agent's LLM)
  "decay_half_life_days": 30,      // optional importance decay
  "dry_run": true                  // preview without persisting
}
// response
{
  "pairs_found": 3, "merges_performed": 2, "decayed_count": 19, "latency_ms": 240,
  "pairs": [
    { "kept_id": "uuid", "kept_content": "...", "superseded_id": "uuid",
      "superseded_content": "...", "similarity": 0.95, "merged_content": "..."|null }
  ]
}
```

---

## Error format

FastAPI default: `{ "detail": "<message>" }` with appropriate HTTP status
(`400` bad request, `401` auth, `403` cross-agent access, `404` not found, `409` conflict,
`502` upstream LLM/extraction failure).

---

## SDK quick reference (Python)

```python
from mneme import Mneme
m = Mneme(api_key="mneme_sk_...", base_url="http://localhost:8000")

m.add("User prefers PyTorch", agent_id="research-bot", user_id="user_42", scope="private")
m.ingest(text="...", user_id="user_42", scope="shared", persist=True)
res = m.search("framework preference?", mode="hybrid", rewrite=True, limit=5)
m.list(agent_id="research-bot"); m.get(id); m.update(id, importance=0.8); m.delete(id)
m.traces(op="search"); m.stats()
```
