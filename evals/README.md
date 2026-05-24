# Mneme — Memory Evals

Two complementary suites that score the memory layer of a **running** Mneme instance.
Both create an isolated `eval` agent, namespace every test under its own `user_id`, and
wipe after themselves — they never touch real data.

Inspired by the standard memory benchmarks (**LongMemEval**, **LOCOMO**): the capability
axes (single-hop, multi-hop, temporal, knowledge-update, abstention) mirror theirs. The
bundled datasets are small/illustrative — swap in a LongMemEval/LOCOMO subset to scale up.

## Phase 1 — deterministic (`run_evals.py`)
No LLM judge → fast, cheap, CI-able. Suites:
| Suite | Measures | Metric |
|---|---|---|
| `retrieval` | does the right memory rank in top-k | recall@k / precision@k / MRR |
| `reconciliation` | does a newer fact supersede a contradicting one | substring proxy (rough — negations confound it) |
| `abstention` | search stays quiet for unrelated queries | top similarity < threshold |
| `extraction` | `/ingest` keeps facts, drops chit-chat | fact count + substrings |

```bash
python3 evals/run_evals.py                 # all
python3 evals/run_evals.py retrieval        # one suite
```
Non-zero exit if any case fails — drop it in CI.

> Note: `reconciliation` here is a *rough proxy* — a correct negation ("no longer at JPMC")
> still contains "JPMC", so substring checks can't fully separate it. For rigorous
> reconciliation/temporal scoring, use Phase 2.

## Phase 2 — end-to-end, LLM-judged (`run_e2e.py`)
Ingests a multi-session conversation → recalls from Mneme → an LLM answers using **only**
recalled memories → an LLM judge grades vs gold, per capability.
```bash
python3 evals/run_e2e.py
```
**The judge dominates the numbers.** A weak judge produces false negatives (we saw 33%→83%
just by hardening JSON parsing). Use a strong judge for trustworthy results.

## Config (env)
| Var | Default | Used by |
|---|---|---|
| `MNEME_URL` | `http://localhost:8000` | both |
| `MNEME_EMAIL` / `MNEME_PASSWORD` | `demo@mneme.dev` / `demo1234` | both |
| `EVAL_EMBED_PROVIDER/MODEL/BASE_URL` | `ollama` / `nomic-embed-text` / `host.docker.internal:11434` | eval agent embeddings |
| `EVAL_LLM_PROVIDER/MODEL/BASE_URL/KEY` | `ollama` / `qwen3:4b` / `host.docker.internal:11434` / "" | eval agent ingest/reconcile |
| `EVAL_JUDGE_URL/MODEL/KEY` | `http://localhost:11434` / `qwen3:4b` / "" | Phase-2 answer + judge (Ollama-compatible `/api/chat`) |

Example with a stronger model (Ollama Cloud):
```bash
EVAL_LLM_MODEL=gemma4:31b EVAL_LLM_BASE_URL=https://ollama.com EVAL_LLM_KEY=$K \
EVAL_JUDGE_MODEL=gemma4:31b EVAL_JUDGE_URL=https://ollama.com EVAL_JUDGE_KEY=$K \
python3 evals/run_e2e.py
```

## Findings so far (gemma4:31b)
- **Retrieval + abstention: strong** (recall@k 1.00; no spurious hits). The retrieval engine is solid.
- **Extraction: model-dependent** — qwen3:4b 3/4 (a JSON-parse failure), gemma 4/4.
- **Knowledge-update (reconciliation): the weak spot** — fails in both suites; a stale fact
  survives and gets recalled. This is the highest-leverage thing to improve (and what plain
  vector stores can't do at all).

## Extending
- Add cases to `datasets/*.json`.
- For real rigor: import a LongMemEval / LOCOMO subset into `datasets/e2e.json`'s shape and
  point the judge at a frontier model.
