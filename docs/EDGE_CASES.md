# Mneme — Edge Cases, Failure Modes & Gotchas

How the system behaves at the boundaries, why, and what to do. Grouped by area.

## 1. Embeddings

### 1.1 Dimension mismatch
**Case:** an agent's embedding provider returns a vector whose length ≠ the tenant's
`embedding_dim` (e.g., tenant is 768 for nomic, but the agent is set to OpenAI
`text-embedding-3-small` = 1536).
**Behavior:** `embed_for_agent` raises `ValueError` with a clear message; the write/search
returns an error rather than corrupting the index.
**Fix:** match models to the tenant dim, or set `EMBEDDING_DIM` in `backend/.env` and
`make reset` (drops the volume — the `vector(N)` column dim is fixed at table creation).

### 1.2 Mixed embeddings within one agent (model changed mid-life)
**Case:** memories written under model A, then the agent switches to model B. Old vectors
are in A-space, new queries in B-space → similarity is noise.
**Fix:** `POST /v1/agents/{slug}/reembed` recomputes all of that agent's vectors with the
current model.

### 1.3 Shared-pool embedding mismatch (the beta caveat)
**Case:** agent A (nomic) writes a `shared` memory; agent B (OpenAI) searches the shared
pool. Their vectors are in different spaces → B's *semantic* leg can't match A's memory.
**Behavior:** cross-model shared **semantic** recall is unreliable; the **lexical** (BM25)
leg still matches because it's model-agnostic.
**Status:** documented **beta**. UI shows a "beta" badge + inline warning.
**GA path:** per-model vector store (a `memory_embeddings(memory_id, model_key, vector)`
table, or Qdrant named vectors) so shared memories are embedded per model.

### 1.4 `fake` provider in production
**Case:** leaving an agent on the default `fake` embedder. Search "works" but rankings are
near-meaningless (hash-based vectors).
**Fix:** `fake` is for demos/tests only. Set a real provider before relying on semantics.

## 2. Reasoning models (Ollama / Qwen3 etc.)

### 2.1 Thinking mode eats the token budget
**Case:** Qwen3 emits `<think>…</think>` before answering; on a small `num_predict`, the
visible `content` comes back empty → extraction "succeeds" with 0 memories, or the test
sample is blank.
**Handled:** Ollama calls pass `think: false`. Structured calls also pass `format: "json"`.
**Residual:** `POST /agents/{slug}/test` may show `llm_ok: true` with an empty `llm_sample`
on a 12-token budget — cosmetic only.

### 2.2 Model narrates instead of returning JSON
**Case:** even with thinking off, small models prepend prose ("We are given… Steps: 1…").
**Handled:** extraction, rewrite, and merge all use **JSON mode** (`format: "json"` /
`response_format`), which grammar-constrains output. `jsonutil.parse_json_lenient` also
strips fences and slices the first `{…}` block as a fallback.

### 2.3 Malformed / empty JSON despite all the above
**Behavior:** `parse_json_lenient` raises `ValueError`; `/ingest` returns `502` with the
raw response prefix; rewrite/merge **fall back** (rewrite → original query, merge → keep
fact A) so search/consolidation never hard-fail on a flaky model.
**Fix:** use a stronger model (`llama3.1:8b`, `qwen2.5:7b`, `gpt-4o-mini`) for extraction.

### 2.4 First-call latency
**Case:** first LLM/embedding call after Ollama idle loads the model (~3–6s on M1).
**Behavior:** request just takes longer; `test` endpoint has a generous timeout.

## 3. Auth & access control

### 3.1 Tenant-wide key + LLM features
**Case:** Memories/Search/Ingest tabs auto-use the **tenant-wide** key, which has no agent
context. Query rewrite / rerank / ingest need an agent's LLM → error
"agent has no LLM configured for rewrite".
**Fix:** click **Use this agent** (agent-scoped key) or pass `agent_id` in the request.

### 3.2 Agent-scoped key trying to escape (`cross_agent: true`)
**Case:** an embedded agent key sets `cross_agent: true` to read everything.
**Behavior:** **ignored** for agent-scoped keys — they stay restricted to `own + shared`.
Only **tenant-wide** keys honor `cross_agent`.

### 3.3 Cross-agent memory fetch by id
**Case:** agent-scoped key calls `GET /v1/memories/{id}` for another agent's private memory.
**Behavior:** `403`.

### 3.4 Expired / invalid JWT
**Behavior:** `401 token expired` / `401 invalid token`. Dashboard redirects to login.

### 3.5 Secret leakage
**Behavior:** third-party API keys are Fernet-encrypted and **never** returned — only
`llm_api_key_set` / `embedding_api_key_set` / `rerank_api_key_set` booleans. PATCH with an
empty string clears a secret; omitting the field keeps it.

## 4. Memory scoping

### 4.1 Memory with no agent (tenant-wide write)
**Case:** tenant-wide key, no `agent_id`, adds a memory → `agent_id` is null.
**Behavior:** allowed (e.g., org-wide knowledge). It surfaces for agent searches only if
`scope = shared`.

### 4.2 `user_id` filter vs shared memories
**Case:** searching with `user_id=user_42` while shared/company memories have
`user_id=null`.
**Behavior (current):** the `user_id` filter is exact, so user-filtered searches exclude
null-user shared memories.
**Implication:** store company-wide shared memory with `user_id=null` and don't over-filter
by user when you want it. (Refinement candidate: exempt `scope=shared` from user filter.)

### 4.3 Deleting an agent
**Behavior:** the agent row is removed; its memories remain (keyed by the slug string). A
new agent with the same slug would re-adopt them. Re-embed if the new agent uses a different
model.

## 5. Consolidation

### 5.1 3+ near-duplicates (clusters)
**Case:** five memories all similar.
**Behavior:** greedy pairwise — highest-sim pair first, then skips any memory already
touched this run. Run consolidation again to collapse further, or lower the threshold.

### 5.2 Over-merging (threshold too low)
**Case:** `similarity_threshold` set low (e.g., 0.75) merges distinct facts.
**Mitigation:** **dry-run defaults to on** in the UI; preview pairs before persisting.
Recommended threshold ≥ 0.9.

### 5.3 LLM merge unavailable
**Case:** `use_llm_merge: true` but the winner's agent has no LLM (or it errors).
**Behavior:** falls back to keeping the winner's content verbatim; the loser is still
superseded. No hard failure.

### 5.4 Re-embedding during merge fails
**Behavior:** keeps the old embedding for the merged memory rather than aborting the run.

### 5.5 Superseded memories
**Behavior:** excluded from all search/list (`superseded_by_id IS NOT NULL`), but retained
in the table for audit. They are not surfaced anywhere in the UI.

### 5.6 Write-time reconciliation — small-model judgment
**Case:** agent has `reconcile` on; a contradicting fact ("now prefers JAX") is written but
the LLM picks `ADD` instead of `UPDATE`/`DELETE`, so the stale fact survives.
**Behavior:** mechanism is correct; the *decision* depends on model quality. 4B models
catch duplicates (NOOP) well but miss contradictions more often.
**Mitigation:** use a stronger LLM for reconcile-enabled agents (`llama3.1:8b`,
`gpt-4o-mini`, `claude-3-5-haiku`). Safe default on any failure is `ADD` (never loses info).
Batch `consolidate` is a backstop that catches near-dups reconciliation missed.

### 5.7 Reconcile cost
**Case:** every write triggers a vector search + (if candidates) an LLM call → latency + $.
**Mitigation:** LLM is only invoked when a near-duplicate exists above the similarity
threshold (default 0.80); brand-new facts skip straight to ADD with no LLM call.

## 5b. Graph memory

### 5b.1 Noisy entities / predicates (small models)
**Case:** 4B models emit malformed entity names (`attention is all you:need`), over-split
relations (`prefers PyTorch` → two edges), or default many entities to `other`.
**Behavior:** stored as-is; dedup is by normalized name+type so variants don't always merge.
**Mitigation:** use a stronger LLM; `POST /v1/graph/rebuild` after switching models.

### 5b.2 Inline extraction failures are silent
**Case:** graph extraction on a single write fails (LLM/JSON error).
**Behavior:** `_maybe_graph` is best-effort — it rolls back the graph changes and the memory
write still succeeds. Nothing surfaces to the caller.
**Mitigation:** `POST /v1/graph/rebuild` reports `errors` count and reprocesses everything.

### 5b.3 Inline extraction latency / cost
**Case:** every write with `graph_enabled` triggers an LLM call (~5–10s local).
**Mitigation:** treat graph memory as opt-in; a background extraction job is on the roadmap.
`rebuild` lets you populate in batch instead of per-write.

### 5b.4 Graph-augmented retrieval — entity linking is name-based
**Case:** `use_graph: true` links query terms to graph entities by name match (whole-name in
query, or a shared token ≥4 chars). Queries that *describe* an entity without naming it
("where is the office") won't link; queries that *name* one ("what does Dheeraj prefer?") do.
**Behavior:** when the graph leg fires, results fuse via RRF (even in `vector`/`lexical`
mode), so absolute scores shift to the RRF range — relative ordering is what matters.
**Mitigation:** combine with `rewrite` to surface entity names, or rely on vector/lexical
legs for descriptive queries. LLM-based entity linking is a future upgrade.

## 6. Search ranking

### 6.1 Lexical leg with an empty/garbage query
**Case:** query with no indexable tokens.
**Behavior:** lexical leg returns nothing; in `hybrid`, vector leg still contributes; in
`lexical` mode, results are empty.

### 6.2 Recency dominating relevance
**Case:** high `recency_weight` (→1) pushes new-but-irrelevant memories to the top.
**Mitigation:** default is 0.15; tune per use case.

### 6.3 Candidate window cutting recall
**Case:** a relevant memory ranks beyond `candidates` (default 30) in both legs.
**Mitigation:** raise `candidates` (cost: more rows fused).

## 7. Platform / ops

### 7.1 Schema changes need a reset
**Case:** adding a column. `create_all` only creates missing **tables**, not new columns.
**Fix:** `make reset` (drops volumes, re-seeds). **Alembic migrations are roadmap** — until
then, schema changes are destructive locally.

### 7.2 Ollama not reachable from the container
**Case:** `connection refused` to `host.docker.internal:11434`.
**Checks:** `ollama serve` running on host; compose has
`extra_hosts: host.docker.internal:host-gateway`; for remote Ollama use the public URL.

### 7.3 Port conflicts
**Case:** 5433/6380/8000/3000 already in use.
**Fix:** edit the port mappings in `docker-compose.yml`.

### 7.4 Demo data vs your data
**Case:** seeded memories use `fake` embeddings (768). Mixing them with nomic-embedded data
makes cross-comparison meaningless.
**Fix:** re-embed (per agent) after switching the agent to a real provider, or work in a
fresh tenant.

### 7.5 No rate limiting / quotas yet
**Behavior:** the API does not throttle. Redis is present but unused for limiting.
**Implication:** don't expose the prototype publicly without a proxy/limiter.

## 8. Data integrity invariants

- A memory always belongs to exactly one tenant.
- `embedding` length always equals the tenant's `embedding_dim` (enforced on write).
- An agent-scoped key can never read another agent's `private` memory (search, list, get).
- Superseded memories never appear in search/list results.
- Secrets are never emitted in any response body.
