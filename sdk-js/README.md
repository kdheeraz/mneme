# @mneme/sdk

TypeScript / Node SDK for [Mneme](../) — memory for LLM agents. Zero runtime dependencies
(uses native `fetch`, Node 18+).

## Install

```bash
# from the monorepo (local dev)
cd sdk-js && npm install && npm run build
```

Once published:

```bash
npm install @mneme/sdk
```

## Quick start

```ts
import { Mneme } from "@mneme/sdk";

const m = new Mneme({
  apiKey: "mneme_sk_...",            // agent-scoped or tenant-wide key
  baseUrl: "http://localhost:8000",  // optional
});

// write
await m.add("User prefers PyTorch over TensorFlow", {
  userId: "user_42",
  kind: "semantic",
  scope: "private",
});

// auto-extract from a conversation (agent must have an LLM configured)
await m.ingest({
  messages: [{ role: "user", content: "I like PyTorch. Always TL;DR my PRs." }],
  userId: "user_42",
});

// hybrid search with optional LLM rewrite + cross-encoder rerank
const res = await m.search("which framework does the user like?", {
  userId: "user_42",
  mode: "hybrid",
  rewrite: true,
  limit: 5,
});
for (const hit of res.hits) {
  console.log(hit.final_score.toFixed(3), hit.memory.content);
}
```

## API

| Method | Returns | Notes |
|--------|---------|-------|
| `add(content, opts?)` | `Memory` | `opts`: agentId, userId, sessionId, kind, scope, meta, importance |
| `ingest(opts)` | `IngestResult` | `messages` or `text`; `persist:false` for dry-run |
| `search(query, opts?)` | `SearchResult` | mode `hybrid`/`vector`/`lexical`; rewrite, rerank, recencyWeight, crossAgent |
| `list(filters?)` | `Memory[]` | agentId, userId, sessionId, kind, limit, offset |
| `get(id)` | `Memory` | |
| `update(id, patch)` | `Memory` | content change re-embeds |
| `delete(id)` | `void` | |
| `traces(filters?)` | `Trace[]` | agentId, op, limit |
| `trace(id)` | `Trace` | |
| `stats()` | `Stats` | |

## Auth

A **tenant-wide** key can address any agent (pass `agentId` per call). An **agent-scoped**
key fixes its agent and can only read `own + shared` memories. Mint keys in the dashboard or
via `POST /v1/keys`.

## Errors

Failed requests throw `MnemeError` with `.status` and `.detail`:

```ts
import { MnemeError } from "@mneme/sdk";
try {
  await m.search("…", { rewrite: true });
} catch (e) {
  if (e instanceof MnemeError) console.error(e.status, e.detail);
}
```

## Notes

- `rewrite` and `rerank` require the agent to have an LLM / reranker configured, and the key
  to resolve to that agent (agent-scoped key, or pass `agentId`).
- `traces` / `stats` work with an API key (read-only, tenant-scoped).
