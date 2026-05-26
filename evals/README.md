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

## Findings — real benchmark (LongMemEval oracle)

The bundled synthetic e2e set turned out too easy to be a fair proxy: the system that
scored ~99% on it scored **41% on LongMemEval oracle-100** (gemma4:31b extract+answer+judge).
Diagnosed via `evals/diag_recall.py` — across 12 sampled failures, **0 were ranking misses**.
The bottleneck was extraction coverage:
- over-abstracted specifics ("User likes seafood" instead of "Grilled Snapper with Mango Salsa"),
- stripped event dates ("User participated in #PlankChallenge" with no date → "X days ago" unanswerable),
- user-centric framing that dropped assistant-provided facts (recommendations, names).

Two fixes, measured on the same 30 oracle items (before/after on identical items):

- `aa030e2` — richer extraction prompt: preserve specifics verbatim, capture both speakers,
  attach absolute dates. `gen_lme.py` now prepends `haystack_dates` to sessions and the
  `question_date` to the question — faithful to the benchmark, which provides both.
- `ed76d9e` — reconcile pre-filter. With more facts per ingest the per-fact reconcile LLM
  call became a 25–60s cascade. The LLM is now consulted only on high-similarity candidates
  (≥0.75) or when the source text carries a change-signal word (`moved`, `no longer`, `now`, ...);
  everything else just ADDs.

| Axis        | Baseline | After  |
|-------------|----------|--------|
| temporal    | 0/6 — 0%   | **6/6 — 100%** |
| single_hop  | 5/11 — 45% | 8/11 — 73%    |
| multi_hop   | 4/5 — 80%  | 4/5 — 80%     |
| update      | 3/6 — 50%  | 4/6 — 67%     |
| abstention  | 2/2 — 100% | 1/2 — 50%     |
| **OVERALL** | **14/30 — 47%** | **23/30 — 77%** (+30 pp) |

Deterministic suites unchanged (gemma4:31b): reconciliation 3/3, extraction 4/4.

**Caveats — don't quote these out of context:**
- Oracle is the evidence-only variant. `longmemeval_s` (~40 distractors per question) is
  the harder headline number; not yet run at scale.
- Two update misses suggest the reconcile gate (`HIGH_SIM_GATE=0.75` + signal words) is too
  narrow on some phrasings — tunable.
- The new extraction prompt is too long for small models (`qwen3:4b` 502s on it); capable
  models (gemma4:31b+) handle it. Per-agent LLM config makes this a docs/defaults question.

Reproduce:
```bash
python3 evals/gen_lme.py --src evals/benchmarks/longmemeval_oracle.json \
    --n 30 --out evals/benchmarks/lme_oracle_small --seed 0
EVAL_DATASET_DIR=evals/benchmarks/lme_oracle_small \
EVAL_LLM_MODEL=gemma4:31b EVAL_LLM_BASE_URL=https://ollama.com EVAL_LLM_KEY=$K \
EVAL_JUDGE_MODEL=gemma4:31b EVAL_JUDGE_URL=https://ollama.com EVAL_JUDGE_KEY=$K \
python3 evals/run_e2e.py
```

## Extending
- Add cases to `datasets/*.json`.
- For real rigor: import a LongMemEval / LOCOMO subset into `datasets/e2e.json`'s shape and
  point the judge at a frontier model.
