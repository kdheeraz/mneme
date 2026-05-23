# Mneme — Low-Level Design (LLD)

Module-by-module internals, the data model, and the algorithms. File paths are relative to
`backend/app/` unless noted.

## 1. Data model

### 1.1 Tables (SQLAlchemy → Postgres)

#### `users` — `models.py:User`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| email | varchar(255) unique, indexed | lowercased on write |
| password_hash | varchar(255) | bcrypt |
| name | varchar(120) | nullable |
| created_at | timestamp | server default now() |

#### `tenants` — `models.py:Tenant`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| name | varchar(120) | |
| owner_user_id | UUID FK→users ON DELETE SET NULL | |
| embedding_dim | int | **vector space dimension for the whole tenant** (default from settings) |
| plan | varchar(32) | default `free` |
| created_at | timestamp | |

#### `agents` — `models.py:Agent`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID FK→tenants ON DELETE CASCADE, indexed | |
| slug | varchar(80) | unique within tenant (`uq_agents_tenant_slug`) |
| name | varchar(120) | |
| description | text | |
| llm_provider | varchar(32) | `none`/`openai`/`anthropic`/`ollama` |
| llm_model | varchar(80) | |
| llm_api_key_enc | text | Fernet-encrypted |
| llm_base_url | varchar(255) | Ollama / OpenAI-compatible URL |
| embedding_provider | varchar(32) | `fake`/`openai`/`ollama` |
| embedding_model | varchar(80) | |
| embedding_api_key_enc | text | Fernet-encrypted |
| embedding_base_url | varchar(255) | |
| rerank_provider | varchar(32) | `none`/`cohere`/`voyage`/`jina` |
| rerank_model | varchar(80) | |
| rerank_api_key_enc | text | Fernet-encrypted |
| auto_extract | bool | hint flag (extraction is explicit via `/ingest`) |
| created_at / updated_at | timestamp | |

#### `api_keys` — `models.py:ApiKey`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID FK→tenants ON DELETE CASCADE, indexed | |
| agent_slug | varchar(80) nullable, indexed | NULL ⇒ tenant-wide key |
| key | varchar(80) unique, indexed | format `mneme_sk_<token_urlsafe(32)>` |
| label | varchar(120) | |
| last_used_at | timestamp | touched on each use |
| created_at | timestamp | |

#### `memories` — `models.py:Memory`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID FK→tenants CASCADE, indexed | |
| agent_id | varchar(120), indexed | = agents.slug (owner / writer) |
| user_id | varchar(120), indexed | optional scope |
| session_id | varchar(120), indexed | optional scope |
| content | text | |
| kind | varchar(32) | `semantic`/`episodic`/`procedural` |
| scope | varchar(16), indexed | `private`/`shared` |
| meta | json | arbitrary tags |
| embedding | `vector(embedding_dim)` | pgvector |
| content_tsv | tsvector GENERATED | `to_tsvector('english', content)`, persisted |
| importance | float | 0..1 |
| created_at / updated_at | timestamp | |
| last_accessed_at | timestamp | bumped on search hit |
| access_count | int | bumped on search hit |
| superseded_by_id | UUID FK→memories SET NULL, indexed | set by consolidation |
| superseded_at | timestamp | |

Indexes: `(tenant_id, agent_id)`, `(tenant_id, user_id)`, GIN on `content_tsv`,
plus the implicit index on `superseded_by_id`, `scope`, `created_at`.

#### `traces` — `models.py:Trace`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| tenant_id | UUID FK→tenants CASCADE, indexed | |
| agent_id / user_id / session_id | varchar | context |
| op | varchar(32) | `add`/`search`/`ingest`/`consolidate` |
| query | text | search/rewrite original query |
| results | json | op-specific payload (hits, meta, extracted items…) |
| latency_ms | int | |
| created_at | timestamp, indexed | |

### 1.2 Why embedding_dim is tenant-level

The `memories.embedding` column is `vector(N)` where `N = settings.embedding_dim`, fixed at
table-creation time. All memories in a deployment share one dimension. Cross-agent shared
search additionally requires the **same model** (not just the same dim) — see
`EDGE_CASES.md §Shared-pool embedding mismatch`.

## 2. Configuration — `config.py`

`Settings` (pydantic-settings, reads env + `backend/.env`):

| Setting | Default | Purpose |
|---------|---------|---------|
| `database_url` | `postgresql+psycopg://mneme:mneme@localhost:5433/mneme` | |
| `redis_url` | `redis://localhost:6380/0` | reserved |
| `embedding_provider` | `fake` | tenant/global default when no agent override |
| `embedding_model` | `text-embedding-3-small` | |
| `embedding_dim` | `1536` (set to `768` for nomic in this deployment) | **vector dim** |
| `openai_api_key` | `""` | global fallback |
| `jwt_secret` / `jwt_alg` / `jwt_ttl_hours` | dev / HS256 / 168 | |
| `fernet_key` | derived from `jwt_secret` if blank | secret encryption |
| `seed_on_boot` | `false` (compose sets `true`) | demo data |

`get_fernet_key()` returns a valid Fernet key — uses `fernet_key` if set, else derives one
deterministically from `jwt_secret` via SHA-256 → urlsafe-base64.

## 3. Auth

### 3.1 User auth — `auth_user.py`
- `hash_password` / `verify_password` — bcrypt.
- `issue_jwt(user_id, tenant_id)` → HS256 token with `sub`, `tenant`, `exp`.
- `decode_jwt` → raises on expiry/invalid.
- `current_user` FastAPI dependency → `(User, Tenant)` from `Authorization: Bearer`.
- `encrypt_secret` / `decrypt_secret` — Fernet for third-party keys.

### 3.2 API-key auth — `auth.py`
- `new_api_key(prefix="mneme_sk")` → `mneme_sk_<token_urlsafe(32)>`.
- `require_key` dependency → `KeyContext(tenant, api_key, bound_agent_slug)`; touches
  `last_used_at`.
- `resolve_agent_for_write(ctx, body_agent_id, db)`:
  - slug = `bound_agent_slug or body_agent_id`
  - if slug set, agent must exist in tenant (404 otherwise)
  - returns `Agent | None` (None ⇒ tenant-wide memory, e.g. for shared knowledge)

`KeyContext` is a dataclass: `{ tenant, api_key, bound_agent_slug }`.

## 4. Embeddings — `embeddings.py`

`embed_for_agent(text, agent, tenant_dim) -> list[float]`:
1. provider/model/api_key/base_url resolved from `agent` (or global defaults if `agent` is None)
2. dispatch:
   - `openai` → OpenAI SDK `embeddings.create` (supports `base_url` override)
   - `ollama` → `POST {base_url}/api/embeddings {model, prompt}` (default base
     `http://host.docker.internal:11434`)
   - else → `_fake_embed` (deterministic, see below)
3. **dimension guard**: if provider returns `len(vec) != tenant_dim`, raises `ValueError`
   with a clear message.

`_fake_embed(text, dim)`: deterministic hash-based vector. Multiple SHA-256 streams fill
`dim` floats in `[-0.5, 0.5)`, plus a tiny token-count / length nudge so near-duplicate
strings cluster slightly; L2-normalized. Not semantically meaningful — for demos/tests
without an API key.

## 5. LLM dispatch — `llm.py`

`chat(agent, messages, max_tokens, json_mode=False) -> str`:
- `openai` → chat.completions; `response_format={"type":"json_object"}` when `json_mode`.
- `anthropic` → messages API; system split out of messages.
- `ollama` → `POST {base_url}/api/chat` with:
  - `think: false` (disables reasoning models like Qwen3 from spending budget on CoT)
  - `format: "json"` when `json_mode` (grammar-constrained JSON)
  - falls back to retry-without-`think` on HTTP 400 (older Ollama)
  - reads `message.content`, falls back to `message.thinking`

Helpers (both JSON-mode + lenient parse, with safe fallbacks):
- `rewrite_query(agent, query)` → `{"query": "..."}` → expanded string (falls back to original)
- `merge_memories(agent, a, b)` → `{"merged": "..."}` → merged string (falls back to `a`)

## 6. Reranking — `rerank.py`

`rerank(agent, query, docs) -> [(orig_index, score), ...]`:
- raises `RerankUnavailable` if provider is `none` or no key.
- providers: `cohere` (`/v2/rerank`), `voyage` (`/v1/rerank`), `jina` (`/v1/rerank`).
- all return `[{index, relevance_score}]`, normalized to tuples.

## 7. JSON parsing — `jsonutil.py`

`parse_json_lenient(raw) -> dict`:
1. strip markdown fences
2. `json.loads`
3. fallback: slice from first `{` to last `}` and retry
4. raise `ValueError` if still unparseable

Shared by `extract.py`, and `llm.py` (rewrite/merge).

## 8. Extraction — `extract.py`

`extract_memories(agent, messages, text, extra_context) -> (list[{content,kind}], raw)`:
1. requires agent LLM (else raises).
2. format conversation: `[ROLE] content` lines, or raw text.
3. `chat(..., max_tokens=1000, json_mode=True)` with a strict system prompt:
   - atomic, self-contained sentences (resolve pronouns)
   - classify `semantic` / `episodic` / `procedural`
   - skip chit-chat; output `{"memories":[{content,kind}]}`
4. `parse_json_lenient` → validate each item; coerce unknown `kind` → `semantic`.

## 9. Search — `main.py:search_memories`

Pipeline (POST `/v1/memories/search`):

1. **Resolve agent** for embed/LLM/rerank config (`bound_agent_slug or body.agent_id`).
2. **Optional rewrite**: `rewrite_query` → `used_query` (falls back to original on error;
   error surfaced in response + trace).
3. **Vector leg** (`mode ∈ {vector, hybrid}`):
   - `embed_for_agent(used_query)`
   - `SELECT memory, 1 - (embedding <=> qvec) AS sim ... ORDER BY embedding <=> qvec LIMIT candidates`
4. **Lexical leg** (`mode ∈ {lexical, hybrid}`):
   - `websearch_to_tsquery('english', used_query)`
   - filter `content_tsv @@ q`, `ORDER BY ts_rank_cd DESC LIMIT candidates`
5. **RRF fuse**: per memory, `rrf += 1/(k + rank)` for each leg it appears in (`k=rrf_k`,
   default 60). Single-mode uses that leg's raw score as `base`.
6. **Optional rerank**: take top `rerank_top_k` by RRF, call reranker on contents, set
   `rerank_score`; on failure, record `rerank_error` and keep RRF order.
7. **Recency boost**: `boost = 0.5 ^ (age_hours / 168)` (1-week half-life).
   `final = (1 - recency_weight)*base + recency_weight*boost`, where `base` is rerank score
   if present, else RRF/leg score.
8. **Sort by final, take `limit`.** Bump `access_count` / `last_accessed_at` on hits.
9. Write `trace(op=search, results={meta, hits[]})`; return `hits + trace_id + rewrite info`.

**Scope filter** (`_apply_scope_filters`, applied to both legs):
```
WHERE tenant_id = :t AND superseded_by_id IS NULL
  -- agent resolved AND not (cross_agent allowed):
  AND (agent_id = :agent OR scope = 'shared')
```
`cross_agent` is honored only when the key is **tenant-wide** (`bound_agent_slug is None`).
Agent-scoped keys are always restricted to `own + shared`.

## 10. Consolidation — `consolidate.py`

`consolidate(db, tenant, similarity_threshold, use_llm_merge, decay_half_life_days, dry_run)`:

1. **find_pairs**: SQL self-join over live (non-superseded) memories within the same
   `(agent_id, user_id)` (NULL-safe via `IS NOT DISTINCT FROM`), where
   `1 - (a.embedding <=> b.embedding) >= threshold`, `a.id < b.id`, ordered by sim, top 500.
2. **greedy merge**: process highest-sim first; skip if either memory already touched.
   - winner = higher `access_count` → higher `importance` → newer `created_at`.
   - if `use_llm_merge` and winner's agent has an LLM: `merge_memories` → replace winner
     content + re-embed.
   - loser: `superseded_by_id = winner.id`, `superseded_at = now`.
3. **decay** (optional): `importance = clamp(importance * 0.5 ^ (age_days / half_life), 0, 1)`
   over live memories (SQL `UPDATE`).
4. `dry_run` computes pairs/merges but commits nothing.

## 11. Bootstrap — `bootstrap.py`

On container start (`python -m app.bootstrap`):
1. `wait_for_db` (retry SELECT 1).
2. `Base.metadata.create_all`.
3. if `seed_on_boot`: `ensure_demo_user` (demo@mneme.dev / demo1234, 4 agents, tenant +
   per-agent keys) then `seed.run()` (16 private + 3 shared demo memories).

## 12. SDK — `sdk-python/mneme/client.py`

`Mneme(api_key, base_url)` — sync `httpx.Client` with `X-API-Key`. Methods:
`add`, `ingest`, `search`, `list`, `get`, `update`, `delete`, `traces`, `trace`, `stats`.
`add`/`ingest` accept `scope`. Mirrors the HTTP API 1:1.

## 13. Frontend — `frontend/`

- `lib/api.ts` — `auth` (localStorage: token, apiKey, user, tenant) + `api` (typed fetch
  wrappers; JWT vs `X-API-Key` per endpoint).
- `app/page.tsx` — login/signup.
- `app/dashboard/layout.tsx` — guards JWT; **auto-selects a tenant-wide API key** so the
  Memories/Search/Ingest tabs work immediately.
- `app/dashboard/page.tsx` — tabs: Overview (+ Consolidation panel), Agents (CRUD + keys +
  test + per-agent config incl. Ollama base URL + reranker), Memories, Live Search (mode /
  rewrite / rerank / recency / cross-agent), Ingest (extraction + shared toggle), Traces.
