#!/usr/bin/env python3
"""Diagnose recall misses: for a failing case, ingest its sessions then check whether
the gold answer is (a) present in the raw sessions, (b) present in the STORED memories
after extraction, (c) present in the TOP-K retrieved set. That three-way split says
whether a miss is an extraction-coverage problem or a ranking problem.

Usage:
  python evals/diag_recall.py --dir evals/benchmarks/lme_oracle_100 \
      --log /tmp/mneme_lme_oracle100.log --only-idk --limit 6 --k 6
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_evals import login, ensure_agent, ingest, search, wipe, _req  # noqa: E402

AGENT = "eval"


def stored_memories(key, uid):
    st, mems = _req("GET", f"/v1/memories?user_id={uid}&limit=500", key=key)
    return [m["content"] for m in (mems or [])]


def tokens(ans: str) -> list[str]:
    # crude key-token set from the gold answer (numbers + capitalized/content words)
    return [w for w in re.findall(r"[A-Za-z0-9$%']+", ans) if len(w) > 2 or w.isdigit()]


def hit(text: str, ans: str) -> bool:
    a = ans.lower().strip()
    if a and a in text.lower():
        return True
    toks = [t.lower() for t in tokens(ans)]
    return bool(toks) and all(t in text.lower() for t in toks)


def failed_idk_names(log_path: str, cases: list[dict], cats: set[str] | None = None) -> list[str]:
    """Map ✗ 'I don't know' rows in the run log back to case names by question prefix."""
    names = []
    for l in open(log_path):
        if "[✗]" not in l or "->" not in l:
            continue
        ans = l.split("->", 1)[1].strip()
        if not ans.strip("'\".").lower().startswith("i don't know"):
            continue
        qprefix = l.split("]", 1)[1].strip()
        # strip the leading category word
        qprefix = qprefix.split(None, 1)[1] if " " in qprefix else qprefix
        qprefix = qprefix.split("->")[0].strip()
        for c in cases:
            if c["questions"][0]["q"].startswith(qprefix[:40]):
                if cats and c["questions"][0]["category"] not in cats:
                    break
                names.append(c["name"])
                break
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--log")
    ap.add_argument("--only-idk", action="store_true")
    ap.add_argument("--cat", help="comma-separated categories to restrict to")
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--k", type=int, default=6)
    a = ap.parse_args()

    ds = json.loads((Path(a.dir) / "e2e.json").read_text())
    cases = {c["name"]: c for c in ds["cases"]}
    cats = set(a.cat.split(",")) if a.cat else None
    if a.only_idk and a.log:
        names = failed_idk_names(a.log, ds["cases"], cats)[: a.limit]
    else:
        names = list(cases)[: a.limit]

    token = login()
    key = ensure_agent(token, reconcile=True)
    tally = {"extraction_miss": 0, "ranking_miss": 0, "in_topk": 0, "not_in_session": 0}
    for name in names:
        c = cases[name]
        q = c["questions"][0]
        uid = f"diag_{name}"
        wipe(key, uid)
        for s in c["sessions"]:
            ingest(key, s, uid, persist=True)
        mems = stored_memories(key, uid)
        hits = search(key, q["q"], "hybrid", uid, a.k)
        topk = [h["memory"]["content"] for h in hits]

        in_session = any(hit(s, q["answer"]) for s in c["sessions"])
        in_stored = any(hit(m, q["answer"]) for m in mems)
        in_topk = any(hit(m, q["answer"]) for m in topk)
        if not in_session:
            verdict = "answer-not-literally-in-session (paraphrase/inferred)"
            tally["not_in_session"] += 1
        elif not in_stored:
            verdict = "EXTRACTION MISS — fact not stored"
            tally["extraction_miss"] += 1
        elif not in_topk:
            verdict = "RANKING MISS — stored but not in top-k"
            tally["ranking_miss"] += 1
        else:
            verdict = "in top-k (answer-LLM should have answered)"
            tally["in_topk"] += 1

        print(f"\n=== {name} [{q['category']}] ===")
        print(f"Q: {q['q']}")
        print(f"gold: {q['answer']!r}")
        print(f"sessions={len(c['sessions'])} stored={len(mems)} | in_session={in_session} in_stored={in_stored} in_topk={in_topk}")
        print(f"VERDICT: {verdict}")
        print("top-k:")
        for i, m in enumerate(topk, 1):
            print(f"  {i}. {m[:100]}")
        wipe(key, uid)

    print("\n==== SUMMARY ====")
    for k, v in tally.items():
        print(f"  {k:<22} {v}")


if __name__ == "__main__":
    main()
