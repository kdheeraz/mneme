# Mneme Documentation

Memory-as-a-Service for LLM agents. This folder is the canonical reference for the system.

| Doc | What it covers |
|-----|----------------|
| [QUICKSTART.md](./QUICKSTART.md) | Stand up the full stack locally with Ollama in ~10 minutes |
| [HLD.md](./HLD.md) | High-level design: architecture, components, data flow, deployment topology |
| [LLD.md](./LLD.md) | Low-level design: data model, module-by-module internals, algorithms |
| [API.md](./API.md) | Complete HTTP API reference with request/response examples |
| [FEATURES.md](./FEATURES.md) | Feature catalog with status (GA / beta / roadmap) |
| [EDGE_CASES.md](./EDGE_CASES.md) | Known edge cases, failure modes, gotchas, and how each is handled |

## TL;DR

Mneme stores, retrieves, and maintains **memory for LLM agents**. Users sign up, register
agents (each with its own LLM / embedding / reranker config), mint API keys, and call a
small HTTP API (or the Python SDK) to add and search memories.

```
┌──────────────┐   X-API-Key    ┌───────────────────────┐   SQL    ┌────────────────────┐
│  Your agents │ ─────────────▶ │  Mneme API (FastAPI)  │ ───────▶ │ Postgres + pgvector│
│  / SDK       │                │                       │          │       Redis        │
└──────────────┘                │  • auth (JWT + keys)  │          └────────────────────┘
                                │  • CRUD + search      │
┌──────────────┐   JWT          │  • rewrite / rerank   │   HTTP   ┌────────────────────┐
│  Dashboard   │ ─────────────▶ │  • extract / merge    │ ───────▶ │  LLM providers     │
│  (Next.js)   │                │  • consolidation      │          │ OpenAI/Anthropic/  │
└──────────────┘                └───────────────────────┘          │ Ollama, rerankers  │
                                                                    └────────────────────┘
```

## Versions

- API version: `0.2.0`
- Storage: Postgres 16 + pgvector
- Backend: FastAPI / SQLAlchemy 2.0 / Python 3.12
- Frontend: Next.js 14 / Tailwind
- Status: pre-launch prototype
