# Mneme — Feature Catalog

Status legend: **GA** = working & stable · **Beta** = working with a documented caveat ·
**Roadmap** = not built yet.

## Identity & multi-tenancy

| Feature | Status | Notes |
|---------|--------|-------|
| User signup / login (JWT) | GA | bcrypt passwords, HS256 tokens, 7-day TTL |
| Workspace (tenant) per user | GA | created at signup; hard isolation boundary |
| Tenant-level embedding dimension | GA | set once; all memories share the dim |
| Team / multi-user per tenant | Roadmap | currently one owner per tenant |
| Plans + Razorpay subscriptions | Built (pending creds) | Free/Pro/Team tiers, subscribe + webhook + Billing UI all wired; awaiting a valid Razorpay test key pair to run a live test-mode charge |
| Plan-limit enforcement | GA | per-tier `agents`/`memories` caps enforced on create-agent, add-memory, and ingest; over-cap writes return HTTP 402. Ingest persists up to the remaining budget and reports `skipped_for_limit` |
| Usage metering | GA | per-tenant `agents`/`memories` counts + plan caps returned by `/v1/billing/status` and `/v1/stats`; dashboard shows usage bars (Billing tab) and caps on Overview cards |
| Overage / metered billing | Roadmap | usage is surfaced but not yet billed beyond hard caps |

## Agents

| Feature | Status | Notes |
|---------|--------|-------|
| Register unlimited agents | GA | unique slug per tenant |
| Per-agent LLM config | GA | none / OpenAI / Anthropic / AWS Bedrock / Ollama (+ base URL). Anthropic & Bedrock share one Messages-API path with JSON-mode enforcement + a prompt-cache breakpoint on the system prefix |
| Per-agent embedding config | GA | fake / OpenAI / Ollama (+ base URL) |
| Per-agent reranker config | GA | none / Cohere / Voyage / Jina |
| Secrets encrypted at rest | GA | Fernet; never returned (only `*_set`) |
| Test connection | GA | probes embedding + LLM, returns sample |
| Re-embed agent memories | GA | after changing embedding model |
| `auto_extract` flag | GA (flag) | extraction itself is explicit via `/ingest` |
| Delete agent | GA | removes the agent's **private** memories + its graph (they're unreachable and only consume quota); **keeps shared** memories (other agents still read them). Returns deleted/kept counts |

## Memory CRUD

| Feature | Status | Notes |
|---------|--------|-------|
| Add memory | GA | content + agent/user/session scope + kind + importance |
| Memory kinds | GA | `semantic` / `episodic` / `procedural` |
| List with filters | GA | agent / user / session / kind; excludes superseded |
| Get / update / delete | GA | update re-embeds on content change |
| Arbitrary metadata (`meta`) | GA | JSON blob |
| Importance score | GA | 0..1, decays via consolidation |
| Access tracking | GA | `access_count`, `last_accessed_at` bumped on hit |

## Retrieval

| Feature | Status | Notes |
|---------|--------|-------|
| Vector search | GA | pgvector cosine |
| Lexical search | GA | Postgres `tsvector` + `ts_rank_cd`, GIN index |
| Hybrid (RRF) | GA | Reciprocal Rank Fusion, k=60, per-leg ranks reported |
| Recency-aware ranking | GA | 1-week half-life boost, tunable `recency_weight` |
| Cross-encoder rerank | GA | Cohere / Voyage / Jina; per-search toggle |
| Query rewriting | GA | agent LLM expands query (JSON mode); graceful fallback |
| Explainable hits | GA | similarity, lexical, RRF, rerank, recency all returned |

## Maintenance / automation

| Feature | Status | Notes |
|---------|--------|-------|
| Auto-extraction (ingest) | GA | conversation/text → atomic memories w/ kinds (JSON mode) |
| Dry-run extraction | GA | `persist: false` |
| Consolidation (dedup) | GA | near-dup pairs per (agent,user), greedy supersede (batch) |
| Write-time reconciliation | GA | per-agent opt-in; LLM picks ADD/UPDATE/DELETE/NOOP on each write (Mem0-style). Quality scales with model size |
| LLM content merge | GA | optional; merges complementary detail |
| Importance decay | GA | half-life decay pass |
| Background scheduler | Roadmap | consolidation is user-triggered today |

## Multi-agent memory

| Feature | Status | Notes |
|---------|--------|-------|
| Per-agent private memory | GA | default scope |
| Shared memory pool | **Beta** | `scope=shared`; every agent in tenant can read |
| Provenance on shared memory | GA | `agent_id` records the writer |
| Agent isolation | GA | agent-scoped keys can't read others' private |
| Cross-agent admin view | GA | tenant-wide key + `cross_agent: true` |
| Cross-agent **semantic** search across **different** embedding models | Roadmap | needs per-model vector store; today same-model only (lexical works cross-model) |

## Graph memory (Mem0g-style)

| Feature | Status | Notes |
|---------|--------|-------|
| Entity + relationship extraction | GA | per-agent opt-in; LLM extracts on write (JSON mode) |
| Graph storage | GA | Postgres tables (`graph_entities`, `graph_relations`), no extra infra |
| Entity dedup | GA | by normalized name + type within (tenant, agent) |
| Graph query API | GA | `GET /v1/graph` (entities + relations) |
| Rebuild from memories | GA | `POST /v1/graph/rebuild` — backfill an agent's existing memories |
| Graph visualization | GA | dashboard **Graph** tab, force-directed SVG, click-to-highlight |
| Extraction quality | Beta | scales with model size; 4B models produce noisy entities/predicates |
| Inline extraction latency | Beta | runs on each write (~5–10s w/ local LLM); background job is roadmap |
| Graph-augmented retrieval | GA | `use_graph: true` adds a third RRF leg — links query entities, traverses 1-hop, surfaces connected memories |

## Providers

| Provider | Embeddings | LLM | Rerank |
|----------|:----------:|:---:|:------:|
| OpenAI | ✓ | ✓ | — |
| Anthropic | — | ✓ | — |
| AWS Bedrock (Claude) | — | ✓ | — |
| Ollama (local/remote) | ✓ | ✓ | — |
| Cohere | — | — | ✓ |
| Voyage | — | — | ✓ |
| Jina | — | — | ✓ |
| `fake` (deterministic) | ✓ | — | — |

Reasoning-model handling: Ollama calls pass `think: false` and (for structured tasks)
`format: "json"` so models like Qwen3 emit clean JSON instead of chain-of-thought.

## Observability

| Feature | Status | Notes |
|---------|--------|-------|
| Operation traces | GA | every add/search/ingest/consolidate, with latency |
| Per-hit scoring in traces | GA | full retrieval reasoning stored |
| Stats endpoint | GA | counts, by-kind, by-agent, ops/24h |
| Dashboard (Overview/Agents/Memories/Search/Ingest/Traces) | GA | Next.js |
| OpenTelemetry / Langfuse export | Roadmap | |

## Clients

| Client | Status | Notes |
|--------|--------|-------|
| HTTP API | GA | OpenAPI at `/docs` |
| Python SDK | GA | `mneme` — Mem0-style call shapes |
| JS/TS SDK | GA | `@mneme/sdk` — zero-dep, native fetch, full types (ESM + CJS) |

## Platform

| Feature | Status | Notes |
|---------|--------|-------|
| Docker Compose (db/redis/api/web) | GA | one-command local stack |
| Schema migrations (Alembic) | Roadmap | currently `create_all` → `make reset` on schema change |
| Redis usage (cache/queue/rate-limit) | Roadmap | container present, reserved |
| TLS / production hardening | Roadmap | terminate at proxy |
