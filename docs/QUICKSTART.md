# Mneme — Quickstart (local, fully offline with Ollama)

Stand up the whole stack on your laptop in ~10 minutes, using **local Ollama** so no API
keys or cloud calls are needed. Tested on Mac mini M1 (16 GB).

## 0. Prerequisites

- **Docker Desktop** running (`docker info` should succeed)
- **Ollama** (https://ollama.com) — `ollama --version`
- ~6 GB free RAM for the LLM, ~3 GB disk for models
- Python 3.11+ (only if you want to run the SDK demo)

## 1. Pull the models

```bash
ollama serve &                    # keep running (skip if already a service)
ollama pull nomic-embed-text      # 137 MB · 768-dim embeddings
ollama pull qwen3:4b              # 2.5 GB · LLM for rewrite/extract/merge
ollama list                       # confirm both are present
```

> Bigger/more reliable LLM if you have the RAM: `ollama pull llama3.1:8b` and use that as
> the LLM model below. Embeddings stay `nomic-embed-text`.

## 2. Configure the embedding dimension

`nomic-embed-text` returns **768-dim** vectors. The tenant vector dimension is fixed at
table-creation, so set it before first boot. Create `/Users/mac/projects/mneme/.env`
(project root — Docker Compose reads it):

```env
EMBEDDING_DIM=768
EMBEDDING_PROVIDER=fake
```

(`fake` is just the default for seed data; agents will be switched to Ollama in step 5.)

## 3. Boot the stack

```bash
cd /Users/mac/projects/mneme
make up                           # builds + starts db, redis, api, web
make logs                         # wait for "Application startup complete", then Ctrl-C
```

Services:

| URL | What |
|-----|------|
| http://localhost:3000 | Dashboard |
| http://localhost:8000/docs | API (Swagger) |

If you changed `EMBEDDING_DIM` after a previous run, do `make reset` (drops volumes,
recreates the schema at the new dim).

## 4. Log in

Open http://localhost:3000 and sign in with the seeded demo account:

```
demo@mneme.dev  /  demo1234
```

It comes with 4 agents and ~19 demo memories (16 private + 3 shared).

## 5. Point the agents at Ollama

Either click through the UI (Agents → expand an agent → set the fields below → Save →
**Test connection**), or run this one-shot script to configure **all** demo agents and
re-embed their memories into one nomic vector space:

```bash
cd /Users/mac/projects/mneme
TOKEN=$(curl -s -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@mneme.dev","password":"demo1234"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

for AG in research-bot support-agent code-assistant sales-agent; do
  curl -s -X PATCH http://localhost:8000/v1/agents/$AG \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{
      "llm_provider":"ollama","llm_model":"qwen3:4b",
      "llm_base_url":"http://host.docker.internal:11434",
      "embedding_provider":"ollama","embedding_model":"nomic-embed-text",
      "embedding_base_url":"http://host.docker.internal:11434"
    }' >/dev/null
  curl -s -X POST http://localhost:8000/v1/agents/$AG/reembed \
    -H "Authorization: Bearer $TOKEN" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['agent'],'re-embedded',d['reembedded'],'/',d['total'])"
done
```

Agent config used:

| Field | Value |
|-------|-------|
| LLM provider / model | `ollama` / `qwen3:4b` |
| LLM base URL | `http://host.docker.internal:11434` |
| Embedding provider / model | `ollama` / `nomic-embed-text` |
| Embedding base URL | `http://host.docker.internal:11434` |

> `host.docker.internal` lets the API container reach Ollama on your host. It works on Mac
> by default; the compose file adds `host-gateway` so it also works on Linux.

## 6. Try it

In the dashboard:

1. **Agents → research-bot → Use this agent** (sets it as the active key for the next tabs).
2. **Live Search** — query *"where is the office located?"* in `vector` mode → you should
   get the **shared** "HQ in Bengaluru" memory (written by support-agent) via semantics.
   Toggle **Query rewrite** to see qwen3 expand the query.
3. **Ingest** — paste a conversation, run extraction → atomic memories appear with
   `semantic`/`episodic`/`procedural` kinds. Tick **Mark as shared** to put them in the
   shared pool.
4. **Overview → Consolidation** — ingest something twice, then preview (dry-run) → run.
5. **Traces** — inspect any operation's full retrieval reasoning.

Or via the SDK:

```bash
pip install -e ./sdk-python httpx
python examples/demo_agent.py
```

## 7. Common ops

```bash
make logs     # tail all services
make ps       # status
make reset    # wipe DB volume + restart (use after EMBEDDING_DIM / schema changes)
make down     # stop
make db-shell # psql into Postgres
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `extraction failed: could not parse JSON` | Use a stronger LLM (`llama3.1:8b`); thinking is already disabled + JSON mode on |
| `rewrite error: agent has no LLM configured` | Active key is tenant-wide → click **Use this agent**, or pass `agent_id` |
| `Embedding dim mismatch ... expects 1536` | You didn't set `EMBEDDING_DIM=768` before boot → set it, `make reset` |
| `connection refused` to `:11434` | `ollama serve` not running, or use a remote Ollama URL |
| Memories tab: `missing X-API-Key header` | Hard-refresh; the dashboard auto-selects a key on login |
| Search results look random | Agent still on `fake` embeddings → set Ollama + run `reembed` |

See [EDGE_CASES.md](./EDGE_CASES.md) for the full list.
