#!/usr/bin/env python3
"""Deterministic eval harness for the Mneme memory layer.

Scores the running Mneme API on four axes (no LLM judge — fast, CI-able):
  retrieval      — recall@k / precision@k / MRR (does the right memory come back?)
  reconciliation — does a newer fact supersede a contradicting older one?
  abstention     — does search stay quiet for unrelated queries?
  extraction     — does /ingest keep durable facts and drop chit-chat?

Zero third-party deps (urllib + json). Runs against an existing account; it creates
a dedicated 'eval' agent, namespaces every test under its own user_id, and wipes
after itself — so it never touches real data.

Usage:
  python evals/run_evals.py                       # all suites
  python evals/run_evals.py retrieval reconciliation
Config via env:
  MNEME_URL (http://localhost:8000), MNEME_EMAIL/MNEME_PASSWORD (demo@mneme.dev/demo1234)
  EVAL_EMBED_PROVIDER/MODEL/BASE_URL  (ollama / nomic-embed-text / http://host.docker.internal:11434)
  EVAL_LLM_PROVIDER/MODEL/BASE_URL/KEY (ollama / qwen3:4b / http://host.docker.internal:11434 / "")
Exit code is non-zero if any case fails its threshold.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("MNEME_URL", "http://localhost:8000").rstrip("/")
EMAIL = os.environ.get("MNEME_EMAIL", "demo@mneme.dev")
PASSWORD = os.environ.get("MNEME_PASSWORD", "demo1234")
DATA_DIR = Path(os.environ.get("EVAL_DATASET_DIR") or (Path(__file__).parent / "datasets"))

AGENT = "eval"
AGENT_CFG = {
    "name": "Eval",
    "embedding_provider": os.environ.get("EVAL_EMBED_PROVIDER", "ollama"),
    "embedding_model": os.environ.get("EVAL_EMBED_MODEL", "nomic-embed-text"),
    "embedding_base_url": os.environ.get("EVAL_EMBED_BASE_URL", "http://host.docker.internal:11434"),
    "llm_provider": os.environ.get("EVAL_LLM_PROVIDER", "ollama"),
    "llm_model": os.environ.get("EVAL_LLM_MODEL", "qwen3:4b"),
    "llm_base_url": os.environ.get("EVAL_LLM_BASE_URL", "http://host.docker.internal:11434"),
    "llm_api_key": os.environ.get("EVAL_LLM_KEY", ""),
}


# ---------- tiny HTTP client ----------

def _req(method, path, token=None, key=None, body=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if key:
        req.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"detail": raw}


def login() -> str:
    st, d = _req("POST", "/v1/auth/login", body={"email": EMAIL, "password": PASSWORD})
    if st != 200:
        die(f"login failed ({st}): {d}")
    return d["access_token"]


def ensure_agent(token, reconcile: bool):
    """Create-or-update the eval agent with the configured providers + reconcile flag."""
    payload = {**AGENT_CFG, "reconcile": reconcile}
    st, _ = _req("GET", f"/v1/agents/{AGENT}", token=token)
    if st == 404:
        _req("POST", "/v1/agents", token=token, body={**payload, "slug": AGENT})
    else:
        _req("PATCH", f"/v1/agents/{AGENT}", token=token, body=payload)
    # ensure an agent-scoped key
    st, keys = _req("GET", f"/v1/keys?agent_slug={AGENT}", token=token)
    if keys:
        return keys[0]["key"]
    st, k = _req("POST", "/v1/keys", token=token, body={"label": "eval", "agent_slug": AGENT})
    return k["key"]


def wipe(key, user_id):
    st, mems = _req("GET", f"/v1/memories?user_id={user_id}&limit=500", key=key)
    for m in mems or []:
        _req("DELETE", f"/v1/memories/{m['id']}", key=key)


def add_memory(key, content, user_id):
    st, m = _req("POST", "/v1/memories", key=key, body={"content": content, "user_id": user_id})
    return m["id"] if st == 200 else None


def ingest(key, text, user_id, persist=True):
    return _req("POST", "/v1/memories/ingest", key=key,
                body={"messages": [{"role": "user", "content": text}], "user_id": user_id, "persist": persist})


def search(key, query, mode, user_id, limit):
    st, d = _req("POST", "/v1/memories/search", key=key,
                 body={"query": query, "mode": mode, "user_id": user_id, "limit": limit})
    return (d or {}).get("hits", []) if st == 200 else []


def die(msg):
    print(f"\n[fatal] {msg}", file=sys.stderr)
    sys.exit(2)


def load(name):
    return json.loads((DATA_DIR / f"{name}.json").read_text())


# ---------- suites ----------

def suite_retrieval(token, key):
    ds = load("retrieval")
    modes = ds.get("modes", ["vector", "hybrid"])
    rows, passed, total = [], 0, 0
    for case in ds["cases"]:
        uid = f"eval_ret_{case['name']}"
        wipe(key, uid)
        ids = [add_memory(key, c, uid) for c in case["memories"]]
        for mode in modes:
            for q in case["queries"]:
                rel = {ids[i] for i in q["relevant"]}
                k = q.get("k", 5)
                hits = search(key, q["query"], mode, uid, k)
                got = [h["memory"]["id"] for h in hits]
                inter = rel & set(got)
                recall = len(inter) / len(rel) if rel else 0.0
                prec = len(inter) / len(got) if got else 0.0
                mrr = 0.0
                for rank, gid in enumerate(got, 1):
                    if gid in rel:
                        mrr = 1.0 / rank
                        break
                ok = recall >= 1.0
                passed += ok
                total += 1
                rows.append((f"{case['name']}/{mode}", q["query"][:34], recall, prec, mrr, ok))
        wipe(key, uid)
    print_section("RETRIEVAL  (recall@k / precision / MRR)")
    print(f"  {'case/mode':<26}{'query':<36}{'recall':>7}{'prec':>6}{'mrr':>6}  ok")
    for name, q, rc, pr, mr, ok in rows:
        print(f"  {name:<26}{q:<36}{rc:>7.2f}{pr:>6.2f}{mr:>6.2f}  {'✓' if ok else '✗'}")
    avg_r = sum(r[2] for r in rows) / len(rows) if rows else 0
    print(f"  → avg recall@k {avg_r:.2f} · {passed}/{total} cases passed")
    return passed, total


def suite_reconciliation(token, key):
    ds = load("reconciliation")
    ensure_agent(token, reconcile=True)  # contradictions need write-time reconcile
    rows, passed, total = [], 0, 0
    for case in ds["cases"]:
        uid = f"eval_rec_{case['name']}"
        wipe(key, uid)
        for stmt in case["ingest"]:
            ingest(key, stmt, uid, persist=True)
        hits = search(key, case["query"], "vector", uid, 10)
        blob = " ".join(h["memory"]["content"] for h in hits).lower()
        miss = [s for s in case.get("should_contain", []) if s.lower() not in blob]
        leak = [s for s in case.get("should_not_contain", []) if s.lower() in blob]
        ok = not miss and not leak
        passed += ok
        total += 1
        rows.append((case["name"], case["query"][:34], miss, leak, ok))
        wipe(key, uid)
    ensure_agent(token, reconcile=False)
    print_section("RECONCILIATION  (newer fact supersedes contradicting older one)")
    for name, q, miss, leak, ok in rows:
        detail = ""
        if miss:
            detail += f" missing={miss}"
        if leak:
            detail += f" leaked={leak}"
        print(f"  {name:<22}{q:<36}{'✓' if ok else '✗'}{detail}")
    print(f"  → {passed}/{total} cases passed")
    return passed, total


def suite_abstention(token, key):
    ds = load("abstention")
    rows, passed, total = [], 0, 0
    for case in ds["cases"]:
        uid = f"eval_abs_{case['name']}"
        wipe(key, uid)
        for c in case["memories"]:
            add_memory(key, c, uid)
        hits = search(key, case["query"], "vector", uid, 5)
        top = hits[0]["similarity"] if hits else 0.0
        thr = case.get("max_similarity", 0.5)
        ok = top < thr
        passed += ok
        total += 1
        rows.append((case["name"], case["query"][:34], top, thr, ok))
        wipe(key, uid)
    print_section("ABSTENTION  (no spurious high-similarity hit for unrelated query)")
    for name, q, top, thr, ok in rows:
        print(f"  {name:<22}{q:<36}top_sim={top:.3f} (<{thr})  {'✓' if ok else '✗'}")
    print(f"  → {passed}/{total} cases passed")
    return passed, total


def suite_extraction(token, key):
    ds = load("extraction")
    rows, passed, total = [], 0, 0
    for case in ds["cases"]:
        uid = "eval_ext"
        st, d = ingest(key, case["input"], uid, persist=False)  # dry-run, nothing stored
        if "extracted" not in (d or {}):
            facts, n = [], -1
        else:
            try:
                facts = [m["content"] for m in json.loads(d.get("raw_llm_response") or "{}").get("memories", [])]
            except Exception:
                facts = []
            n = d["extracted"]
        if n == -1:
            ok = False  # ingest errored (e.g. model JSON parse failure) — not a clean result
        else:
            ok = True
            if "max_facts" in case:
                ok = ok and n <= case["max_facts"]
            if "min_facts" in case:
                ok = ok and n >= case["min_facts"]
            if case.get("expect_any"):
                blob = " ".join(facts).lower()
                ok = ok and any(e.lower() in blob for e in case["expect_any"])
        passed += ok
        total += 1
        rows.append((case["name"], case["input"][:34], n, ok))
    print_section("EXTRACTION  (keep durable facts, drop chit-chat/questions)")
    for name, inp, n, ok in rows:
        shown = "ERR" if n == -1 else str(n)
        print(f"  {name:<22}{inp:<36}extracted={shown:<4}{'✓' if ok else '✗'}")
    print(f"  → {passed}/{total} cases passed")
    return passed, total


def print_section(title):
    print(f"\n=== {title} ===")


SUITES = {
    "retrieval": suite_retrieval,
    "reconciliation": suite_reconciliation,
    "abstention": suite_abstention,
    "extraction": suite_extraction,
}


def main():
    which = [a for a in sys.argv[1:] if not a.startswith("-")] or list(SUITES)
    bad = [w for w in which if w not in SUITES]
    if bad:
        die(f"unknown suite(s): {bad}. choose from {list(SUITES)}")
    print(f"Mneme evals · {BASE} · agent='{AGENT}' · embed={AGENT_CFG['embedding_model']} llm={AGENT_CFG['llm_model']}")
    token = login()
    key = ensure_agent(token, reconcile=False)
    p_total = t_total = 0
    for name in which:
        p, t = SUITES[name](token, key)
        p_total += p
        t_total += t
    print(f"\n{'='*60}\nTOTAL: {p_total}/{t_total} cases passed")
    sys.exit(0 if p_total == t_total else 1)


if __name__ == "__main__":
    main()
