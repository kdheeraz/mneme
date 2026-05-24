#!/usr/bin/env python3
"""Generate a larger synthetic eval set from templated personas.

Writes retrieval / reconciliation / abstention / e2e datasets to a target dir, so you
can run the harness at scale:  EVAL_DATASET_DIR=evals/datasets_large python3 evals/run_evals.py

  python3 evals/gen_dataset.py --personas 20 --out evals/datasets_large [--seed 7]
"""
import argparse
import json
import random
from pathlib import Path

FIRST = ["Dheeraj", "Aisha", "Marco", "Lena", "Kenji", "Priya", "Tomas", "Sara", "Omar",
         "Mei", "Noah", "Ava", "Liam", "Zara", "Ivan", "Nora", "Hugo", "Fatima", "Diego",
         "Yuki", "Raj", "Elena", "Sam", "Ravi", "Ana", "Leo", "Iris", "Kai", "Nina", "Theo"]
CITIES = ["Bangalore", "Berlin", "Lisbon", "Tokyo", "Austin", "Toronto", "Nairobi",
          "Dublin", "Madrid", "Singapore", "Pune", "Amsterdam"]
EMPLOYERS = ["JPMC", "Microsoft", "Acme", "Stripe", "Google", "Infosys", "Datadog",
             "Shopify", "Netflix", "Adobe"]
JOBS = ["software engineer", "data scientist", "product manager", "designer",
        "site reliability engineer", "machine learning researcher"]
DIETS = ["vegetarian", "vegan", "pescatarian"]
LANGS = ["Rust", "Python", "Go", "TypeScript", "Kotlin", "Elixir"]
PETS = [("dog", "Pixel"), ("cat", "Mango"), ("dog", "Bo"), ("cat", "Luna"), ("parrot", "Kiwi")]
HOBBIES = ["hiking", "rock climbing", "painting", "cycling", "chess", "photography"]


def persona(rng):
    return dict(
        name=rng.choice(FIRST), city=rng.choice(CITIES), emp=rng.choice(EMPLOYERS),
        job=rng.choice(JOBS), diet=rng.choice(DIETS), lang=rng.choice(LANGS),
        pet=rng.choice(PETS), hobby=rng.choice(HOBBIES),
    )


def retrieval(rng, n):
    cases = []
    for i in range(n):
        p = persona(rng)
        mems = [
            f"User's name is {p['name']}",
            f"User lives in {p['city']}",
            f"User works as a {p['job']} at {p['emp']}",
            f"User is {p['diet']}",
            f"User's favorite programming language is {p['lang']}",
            f"User has a {p['pet'][0]} named {p['pet'][1]}",
            f"User enjoys {p['hobby']}",
        ]
        cases.append({"name": f"p{i}", "memories": mems, "queries": [
            {"query": "what is the user's name?", "relevant": [0], "k": 3},
            {"query": "which city does the user live in?", "relevant": [1], "k": 3},
            {"query": "where does the user work?", "relevant": [2], "k": 3},
            {"query": "what is the user's diet?", "relevant": [3], "k": 3},
            {"query": "what programming language does the user prefer?", "relevant": [4], "k": 3},
        ]})
    return {"description": "generated retrieval set", "modes": ["hybrid"], "cases": cases}


def reconciliation(rng, n):
    cases = []
    for i in range(n):
        kind = rng.choice(["employer", "city", "diet", "job"])
        if kind == "employer":
            a, b = rng.sample(EMPLOYERS, 2)
            cases.append({"name": f"emp{i}", "ingest": [f"I work at {a}.", f"Update: I left {a}, I now work at {b}."],
                          "query": "where does the user work?", "should_contain": [b], "should_not_contain": [f"works at {a}"]})
        elif kind == "city":
            a, b = rng.sample(CITIES, 2)
            cases.append({"name": f"city{i}", "ingest": [f"I live in {a}.", f"I moved to {b} recently."],
                          "query": "where does the user live?", "should_contain": [b], "should_not_contain": [f"lives in {a}"]})
        elif kind == "diet":
            a, b = rng.sample(DIETS, 2)
            cases.append({"name": f"diet{i}", "ingest": [f"I am {a}.", f"I'm not {a} anymore, I'm {b} now."],
                          "query": "what is the user's diet?", "should_contain": [b], "should_not_contain": [f"is {a}"]})
        else:
            a, b = rng.sample(JOBS, 2)
            cases.append({"name": f"job{i}", "ingest": [f"I'm a {a}.", f"I switched roles — I'm a {b} now."],
                          "query": "what is the user's job?", "should_contain": [b], "should_not_contain": [f"is a {a}"]})
    return {"description": "generated reconciliation set", "cases": cases}


def abstention(rng, n):
    unrelated = ["what is the user's bank account number?", "what is the user's blood type?",
                 "what is the user's passport number?", "what medication does the user take?",
                 "what is the user's home alarm code?"]
    cases = []
    for i in range(n):
        p = persona(rng)
        cases.append({"name": f"abs{i}",
                      "memories": [f"User lives in {p['city']}", f"User is {p['diet']}", f"User enjoys {p['hobby']}"],
                      "query": rng.choice(unrelated), "max_similarity": 0.55})
    return {"description": "generated abstention set", "cases": cases}


def e2e(rng, n):
    cases = []
    for i in range(n):
        p = persona(rng)
        a_emp = p["emp"]
        b_emp = rng.choice([e for e in EMPLOYERS if e != a_emp])
        cases.append({"name": f"e{i}", "sessions": [
            f"Hi, I'm {p['name']}. I live in {p['city']} and I work as a {p['job']} at {a_emp}.",
            f"I'm {p['diet']} and I really enjoy {p['hobby']}.",
            f"Update: I accepted an offer at {b_emp}, so I'm leaving {a_emp}.",
            f"We got a {p['pet'][0]} — her name is {p['pet'][1]}.",
        ], "questions": [
            {"q": "What is the user's name?", "answer": p["name"], "category": "single_hop"},
            {"q": "What is the user's pet's name?", "answer": p["pet"][1], "category": "single_hop"},
            {"q": "Where does the user currently work?", "answer": b_emp, "category": "update"},
            {"q": f"Is the user {p['diet']} and do they have a pet?",
             "answer": f"Yes — {p['diet']} with a {p['pet'][0]} named {p['pet'][1]}", "category": "multi_hop"},
            {"q": "What is the user's shoe size?", "answer": "Not stated", "category": "abstention"},
        ]})
    return {"description": "generated e2e set", "cases": cases}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--personas", type=int, default=20)
    ap.add_argument("--out", default="evals/datasets_large")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "retrieval.json").write_text(json.dumps(retrieval(rng, a.personas), indent=2))
    (out / "reconciliation.json").write_text(json.dumps(reconciliation(rng, max(8, a.personas)), indent=2))
    (out / "abstention.json").write_text(json.dumps(abstention(rng, max(8, a.personas)), indent=2))
    (out / "e2e.json").write_text(json.dumps(e2e(rng, max(8, a.personas)), indent=2))
    print(f"wrote to {out}/  ·  retrieval={a.personas}p×5q  reconciliation={max(8,a.personas)}  "
          f"abstention={max(8,a.personas)}  e2e={max(8,a.personas)}×5q")


if __name__ == "__main__":
    main()
