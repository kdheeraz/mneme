# Mneme

**Memory-as-a-Service for LLM agents.**

- Users sign up → get a workspace (tenant)
- Register unlimited **agents**, each with its own LLM + embedding config
- Generate **per-agent API keys** (or tenant-wide keys) and rotate at will
- One API for `add` / `search` / `update` / `delete` of memories with full provenance
- Built-in observability: every retrieval is logged with similarity + recency scores
- Multi-agent shared memory and cross-agent search

> Working name. Pick a real one before launch.

**Full docs:** [docs/](./docs/) — [HLD](./docs/HLD.md) · [LLD](./docs/LLD.md) · [API](./docs/API.md) · [Features](./docs/FEATURES.md) · [Edge cases](./docs/EDGE_CASES.md)

```
┌─────────────────┐     ┌─────────────────────────────────┐     ┌────────────────────┐
│  user signs up  │     │   Mneme API                     │ ──▶ │ Postgres + pgvector│
│       │         │     │  • JWT auth (user dashboard)    │     │       Redis        │
│       ▼         │     │  • X-API-Key auth (agents/SDK)  │     └────────────────────┘
│  register agent │ ──▶ │  • multi-tenant + multi-agent   │
│  + LLM config   │     │  • per-agent embedding dispatch │
│  + emb config   │     │  • observability traces         │
│       │         │     └─────────────────────────────────┘
│       ▼         │
│  agent API key  │  ──▶  use in SDK / your agent code
└─────────────────┘
```

## Stack

- **Backend**: FastAPI · SQLAlchemy 2.0 · pgvector
- **Storage**: Postgres 16 (pgvector) · Redis
- **Auth**: JWT (users) + API keys (agents). Per-agent third-party keys encrypted at rest (Fernet).
- **Embeddings**: per-agent — `openai` or built-in deterministic `fake` (no key needed)
- **SDK**: Python (Mem0-compatible call shapes)
- **Dashboard**: Next.js 14 · Tailwind
- **Infra**: Docker Compose

## Prereqs

- Docker Desktop
- Python 3.11+ (for the SDK / demo script)

## Quickstart

```bash
cd /Users/mac/projects/mneme

# 1. boot Postgres + Redis + API + Web
make up
make logs     # wait for "Application startup complete", then Ctrl-C

# 2. open the dashboard
open http://localhost:3000
```

On first boot a demo user is auto-created:

| | |
|---|---|
| Email | `demo@mneme.dev` |
| Password | `demo1234` |
| Pre-seeded | 4 agents · 16 memories · tenant + per-agent API keys |

Sign in with those (or click **Sign up** to make your own account from scratch).

## The dashboard

Five tabs:

1. **Overview** — total agents, memories, ops/24h, top agents bar chart
2. **Agents** — register new agents with their own LLM + embedding config; expand any row to edit config or manage API keys. Click *"Use this agent"* to set its key as active for the next three tabs.
3. **Memories** — list / filter / delete memories (uses the active API key)
4. **Live Search** — type a query, see ranked hits with similarity + recency boost + final score
5. **Traces** — every API call logged, expand for full retrieval reasoning

## Registering an agent (UI)

```
Agents tab → + New agent
  name:                Research Bot
  slug:                research-bot       (auto if blank)
  description:         Reads papers, summarizes…
  llm_provider:        openai             (or anthropic / none)
  llm_model:           gpt-4o-mini
  llm_api_key:         sk-…               (encrypted at rest)
  embedding_provider:  openai             (or fake)
  embedding_model:     text-embedding-3-small
  embedding_api_key:   sk-…
  auto_extract:        ☐
→ "Create + generate API key"
```

You can also use a tenant-wide key (no `agent_slug`) and pass `agent_id` in each API call.

## SDK usage

```python
from mneme import Mneme

# agent-scoped key — agent_id is implicit
m = Mneme(api_key="mneme_sk_<agent_key>")
m.add("User prefers PyTorch over TensorFlow", user_id="user_42")
res = m.search("which framework?", user_id="user_42")

# OR: tenant-wide key — pass agent_id explicitly
m = Mneme(api_key="mneme_sk_<tenant_key>")
m.add("User prefers PyTorch", agent_id="research-bot", user_id="user_42")
```

Run the end-to-end demo:

```
make demo
```

## API surface

### Auth (JWT)
| Method | Path                     |
|--------|--------------------------|
| POST   | `/v1/auth/signup`        |
| POST   | `/v1/auth/login`         |
| GET    | `/v1/auth/me`            |

### Agents (JWT)
| Method | Path                     |
|--------|--------------------------|
| POST   | `/v1/agents`             |
| GET    | `/v1/agents`             |
| GET    | `/v1/agents/{slug}`      |
| PATCH  | `/v1/agents/{slug}`      |
| DELETE | `/v1/agents/{slug}`      |

### API keys (JWT)
| Method | Path                     |
|--------|--------------------------|
| POST   | `/v1/keys`               |
| GET    | `/v1/keys?agent_slug=…`  |
| DELETE | `/v1/keys/{id}`          |

### Memories (X-API-Key)
| Method | Path                          |
|--------|-------------------------------|
| POST   | `/v1/memories`                |
| GET    | `/v1/memories?…`              |
| GET    | `/v1/memories/{id}`           |
| PATCH  | `/v1/memories/{id}`           |
| DELETE | `/v1/memories/{id}`           |
| POST   | `/v1/memories/search`         |

### Observability (JWT)
| Method | Path                     |
|--------|--------------------------|
| GET    | `/v1/traces`             |
| GET    | `/v1/traces/{id}`        |
| GET    | `/v1/stats`              |

Full Swagger: http://localhost:8000/docs

## Shared memory pool (beta)

Memories carry a `scope`: `private` (only the owning agent) or `shared` (every agent in
the tenant). Each agent's search returns its own private memories **+** the shared pool.
Agent-scoped keys cannot escape `own + shared`; only tenant-wide keys can read all
private memories (`cross_agent: true`).

**Beta caveat:** cross-agent *semantic* search is only correct when the agents involved
use the **same embedding model** — vectors from different models live in different spaces
and aren't comparable. Cross-model shared search still works via the lexical (BM25) leg.

Roadmap to GA: per-agent private embeddings + a per-model vector store (Option A: a
`memory_embeddings(memory_id, model_key, vector)` table, or Qdrant named vectors) so
agents can use different embedders while shared semantic search stays correct.

## Multi-tenancy model

- Every API call resolves to **exactly one tenant** (via JWT for dashboard, via API key for SDK)
- Within a tenant, memories are keyed by `(agent_id, user_id, session_id)` — all optional
- Agent-scoped keys force `agent_id` so they can never see other agents' data
- Tenant-wide keys can read/write any agent in the tenant (admin / cross-agent scenarios)

## Per-agent isolation

| Concern | Mechanism |
|---|---|
| Memory data | `tenant_id` row filter on every query |
| Agent boundary | API key's `agent_slug` (when set) overrides any agent_id in request |
| LLM key isolation | Stored encrypted (Fernet) per-agent |
| Embedding dim | Per-tenant constant (set at signup) — all agents in a tenant share it |

## Common ops

```bash
make up       # start
make down     # stop
make reset    # nuke DB volume + restart fresh (use after schema changes)
make logs     # tail logs
make demo     # run the example agent script
make db-shell # psql into the DB
```

## What's still missing (roadmap)

1. **Auto-memory extraction** — when an agent has `auto_extract=true`, use its LLM to extract atomic memories from raw conversation
2. **Memory consolidation** — background dedup, merge, decay
3. **Cognitive memory model** — separate semantic / episodic / procedural retrieval rules
4. **Provenance graph view** — UI showing which agent wrote/read each memory
5. **Memory eval suite** — recall@k benchmarks per tenant
6. **PII redaction at write-time** (enterprise tier)
7. **JS/TS SDK**
8. **Stripe billing** + plan tiers + usage metering
9. **Alembic migrations** (currently using `create_all`)
