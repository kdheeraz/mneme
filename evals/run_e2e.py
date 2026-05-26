#!/usr/bin/env python3
"""Phase-2 end-to-end memory eval (LLM-judged) — LongMemEval / LOCOMO style.

For each case: ingest a multi-session conversation into Mneme (reconcile on, so the
memory updates as facts change), then for each question:
  1. recall relevant memories from Mneme (hybrid search),
  2. an LLM answers using ONLY those recalled memories,
  3. an LLM judge grades the answer vs the gold answer.
Reports accuracy by capability: single_hop, multi_hop, temporal, update, abstention.

Unlike the deterministic suite, this measures the END result — "can the system
actually answer correctly" — which is the honest way to score reconciliation/temporal.

LLM (answer + judge) is any Ollama-compatible /api/chat endpoint:
  EVAL_JUDGE_URL (http://localhost:11434)  EVAL_JUDGE_MODEL (qwen3:4b)  EVAL_JUDGE_KEY ("")
The Mneme eval agent (ingest extraction + recall) is configured via run_evals' EVAL_* envs.
Tip: use a strong model (e.g. gemma4:31b on https://ollama.com) for trustworthy judging.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Eval tool talking to a model endpoint — tolerate hosts where the local Python
# lacks CA certs (common on macOS). Not a data-plane path, so skipping verify is fine.
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

sys.path.insert(0, str(Path(__file__).parent))
from run_evals import login, ensure_agent, ingest, search, wipe, BASE, DATA_DIR  # noqa: E402

JUDGE_URL = os.environ.get("EVAL_JUDGE_URL", "http://localhost:11434").rstrip("/")
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "qwen3:4b")
JUDGE_KEY = os.environ.get("EVAL_JUDGE_KEY", "")


def _llm(messages, json_mode=False, max_tokens=400) -> str:
    body = {"model": JUDGE_MODEL, "messages": messages, "stream": False,
            "think": False, "options": {"num_predict": max_tokens}}
    if json_mode:
        body["format"] = "json"
    req = urllib.request.Request(JUDGE_URL + "/api/chat", data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    if JUDGE_KEY:
        req.add_header("Authorization", f"Bearer {JUDGE_KEY}")
    try:
        with urllib.request.urlopen(req, timeout=180, context=_SSL) as r:
            d = json.loads(r.read().decode())
        return ((d.get("message") or {}).get("content") or "").strip()
    except Exception as e:
        return f"[llm error: {e}]"


def answer(memories, question) -> str:
    ctx = "\n".join(f"- {m}" for m in memories) or "(no relevant memories)"
    sys_p = ("You are an assistant answering questions about a user using ONLY the memory "
             "notes provided. If the answer is not supported by the notes, reply exactly: "
             "I don't know. Be concise.")
    return _llm([
        {"role": "system", "content": sys_p},
        {"role": "user", "content": f"Memory notes:\n{ctx}\n\nQuestion: {question}"},
    ])


def judge(question, reference, candidate, category) -> bool:
    if category == "abstention":
        sys_p = ('Did the assistant correctly decline to answer (e.g. "I don\'t know") '
                 'because the info was unavailable? Reply JSON only: {"correct": true|false}.')
        user_p = f"Question: {question}\nAssistant answer: {candidate}"
    else:
        sys_p = ('You grade answers. Is the CANDIDATE correct given the REFERENCE? Accept '
                 'paraphrases and semantically equivalent answers. Reply JSON only: '
                 '{"correct": true|false}.')
        user_p = f"Question: {question}\nReference: {reference}\nCandidate: {candidate}"
    raw = _llm([{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
               json_mode=True, max_tokens=60).strip()
    try:
        return bool(json.loads(raw).get("correct"))
    except Exception:
        # Lenient fallback when the judge doesn't return clean JSON (small models drift).
        r = raw.lower()
        if "incorrect" in r or "false" in r:
            return False
        return "correct" in r or "true" in r or "yes" in r


def main():
    reconcile = os.environ.get("EVAL_RECONCILE", "1") not in ("0", "false", "no")
    print(f"Mneme E2E eval · {BASE} · answer+judge={JUDGE_MODEL} · reconcile={reconcile}")
    token = login()
    key = ensure_agent(token, reconcile=reconcile)
    ds = json.loads((DATA_DIR / "e2e.json").read_text())
    cats: dict[str, list[int]] = {}
    rows = []
    for case in ds["cases"]:
        uid = f"eval_e2e_{case['name']}"
        wipe(key, uid)
        for s in case["sessions"]:
            ingest(key, s, uid, persist=True)
        for q in case["questions"]:
            hits = search(key, q["q"], "hybrid", uid, 6)
            mems = [h["memory"]["content"] for h in hits]
            ans = answer(mems, q["q"])
            ok = judge(q["q"], q.get("answer", ""), ans, q["category"])
            c = cats.setdefault(q["category"], [0, 0])
            c[0] += int(ok)
            c[1] += 1
            rows.append((q["category"], q["q"], ans, ok))
        wipe(key, uid)

    print()
    for cat, q, ans, ok in rows:
        print(f"  [{'✓' if ok else '✗'}] {cat:<11} {q[:44]:<46} -> {ans[:54]!r}")
    print("\n  capability          accuracy")
    tp = tt = 0
    for cat, (p, t) in sorted(cats.items()):
        tp += p
        tt += t
        print(f"  {cat:<18}  {p}/{t}  {round(p / t * 100)}%")
    print(f"  {'OVERALL':<18}  {tp}/{tt}  {round(tp / tt * 100) if tt else 0}%")
    sys.exit(0 if tp == tt else 1)


if __name__ == "__main__":
    main()
