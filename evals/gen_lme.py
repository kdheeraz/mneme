#!/usr/bin/env python3
"""Convert a LongMemEval file (oracle / s_cleaned) into the harness e2e.json shape.

Stratified-samples N questions proportional to the harness capability axes (or rebuilds
an exact set via --names-file) and writes <out>/e2e.json that run_e2e.py consumes via
EVAL_DATASET_DIR. One LongMemEval question becomes one case (it carries its own haystack),
so each case has exactly one question.

Date grounding (faithful to the benchmark, which provides both):
  - each session is prefixed with its haystack date as '[Date: ...]' so the extractor can
    attach absolute dates to events and resolve relative references;
  - the question is suffixed with '(Today's date is <question_date>.)' so "how many days
    ago / which happened first" questions have a 'now' reference.

LongMemEval type -> harness axis:
  single-session-{user,assistant,preference} -> single_hop
  multi-session                              -> multi_hop
  temporal-reasoning                         -> temporal
  knowledge-update                           -> update
  question_id ending in _abs (unanswerable)  -> abstention   (overrides the above)

Usage:
  python evals/gen_lme.py --src evals/benchmarks/longmemeval_oracle.json \
      --n 100 --out evals/benchmarks/lme_oracle_100 --seed 0
  python evals/gen_lme.py --src evals/benchmarks/longmemeval_oracle.json \
      --names-file /tmp/first30.json --out evals/benchmarks/lme_oracle_small
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

TYPE_MAP = {
    "single-session-user": "single_hop",
    "single-session-assistant": "single_hop",
    "single-session-preference": "single_hop",
    "multi-session": "multi_hop",
    "temporal-reasoning": "temporal",
    "knowledge-update": "update",
}


def category(e: dict) -> str:
    if str(e.get("question_id", "")).endswith("_abs"):
        return "abstention"
    return TYPE_MAP.get(e["question_type"], "single_hop")


def session_text(sess: list[dict], date: str | None) -> str:
    head = f"[Date: {date}]\n" if date else ""
    return head + "\n".join(f"{t['role']}: {t['content']}" for t in sess)


def to_case(e: dict) -> dict:
    dates = e.get("haystack_dates") or []
    sessions = [session_text(s, dates[i] if i < len(dates) else None)
                for i, s in enumerate(e["haystack_sessions"])]
    q = e["question"]
    qd = e.get("question_date")
    if qd:
        q = f"{q} (Today's date is {qd}.)"
    return {
        "name": e["question_id"],
        "sessions": sessions,
        "questions": [{"q": q, "answer": e["answer"], "category": category(e)}],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--names-file", help="JSON list of question_ids to rebuild exactly (ignores --n)")
    a = ap.parse_args()

    data = json.load(open(a.src))

    if a.names_file:
        want = set(json.load(open(a.names_file)))
        by_id = {e["question_id"]: e for e in data}
        cases = [to_case(by_id[n]) for n in json.load(open(a.names_file)) if n in by_id]
        counts = {}
        for c in cases:
            counts[c["questions"][0]["category"]] = counts.get(c["questions"][0]["category"], 0) + 1
    else:
        buckets: dict[str, list] = defaultdict(list)
        for e in data:
            buckets[category(e)].append(e)
        total = len(data)
        raw = {c: len(v) / total * a.n for c, v in buckets.items()}
        alloc = {c: int(x) for c, x in raw.items()}
        for c, _ in sorted(raw.items(), key=lambda kv: kv[1] - int(kv[1]), reverse=True)[: a.n - sum(alloc.values())]:
            alloc[c] += 1
        rng = random.Random(a.seed)
        cases, counts = [], {}
        for c, items in buckets.items():
            k = min(alloc[c], len(items))
            counts[c] = k
            for e in rng.sample(items, k):
                cases.append(to_case(e))
        rng.shuffle(cases)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "e2e.json").write_text(json.dumps({"cases": cases}, indent=2))
    print(f"source={a.src}" + (f" names-file={a.names_file}" if a.names_file else f" n={a.n} seed={a.seed}"))
    print("allocation:", dict(sorted(counts.items())), "→ total cases:", len(cases))


if __name__ == "__main__":
    main()
