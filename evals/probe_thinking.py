#!/usr/bin/env python3
"""A/B probe: does enabling 'thinking' improve the reconcile DECISION on indirect
phrasing — without enumerating change-phrases in the prompt?

Calls the model directly with the EXACT production DECISION_SYSTEM prompt on hard
cases where the supersede signal is implicit ("accepted an offer at X", "relocated
to Y", "Sam is my ex"). Runs each case think-off then think-on and compares.

Isolates the decision from extraction/recall/answer noise, and is cheap (no judge).

  EVAL_LLM_MODEL=gemma4:31b EVAL_LLM_BASE_URL=https://ollama.com EVAL_LLM_KEY=... \
      python3 evals/probe_thinking.py
"""
import json
import os
import ssl
import urllib.request

MODEL = os.environ.get("EVAL_LLM_MODEL", "gemma4:31b")
URL = os.environ.get("EVAL_LLM_BASE_URL", "https://ollama.com").rstrip("/")
KEY = os.environ.get("EVAL_LLM_KEY", "")

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

# EXACT production prompt (backend/app/reconcile.py) — keep in sync.
DECISION_SYSTEM = (
    "You manage an AI agent's long-term memory. The EXISTING memories represent the user's "
    "CURRENT state. Given a NEW fact and the most similar EXISTING memories, choose exactly "
    "ONE operation:\n"
    "- ADD: the new fact is genuinely new information that does not conflict with any existing memory.\n"
    "- NOOP: the new fact is already fully captured by an existing memory.\n"
    "- UPDATE: the new fact refines or extends ONE existing memory (merge them).\n"
    "- DELETE: the new fact changes or obsoletes ONE existing memory — pick the stale memory "
    "as target_id so it is replaced.\n"
    "Single-valued attributes (employer, home city, job title, marital status, current diet, "
    "etc.) have only ONE current value: if the new fact gives a different value for such an "
    "attribute, you MUST DELETE the existing memory that asserts the old value — never keep both. "
    "Change signals like 'left', 'moved', 'no longer', 'now', 'switched', 'previously', 'used to' "
    "mean the prior state is stale.\n"
    'Return JSON only: {"operation":"ADD|NOOP|UPDATE|DELETE",'
    '"target_id":"<id of the existing memory for UPDATE/DELETE, else null>",'
    '"content":"<final memory text to store for ADD/UPDATE/DELETE, else null>",'
    '"reason":"<one short clause>"}'
)

# Each case: existing memory, the NEW fact, and the operations we accept as correct.
# "supersede" cases use indirect phrasing — the model must INFER the implied current value.
CASES = [
    # --- indirect supersede (must DELETE the stale single-valued memory) ---
    ("User works at Acme", "User accepted an offer at Netflix", {"DELETE"}, "supersede"),
    ("User works at Acme", "User is starting at Stripe next month", {"DELETE"}, "supersede"),
    ("User works at Acme", "User is leaving Acme", {"DELETE"}, "supersede"),
    ("User works at Acme", "User signed with Google", {"DELETE"}, "supersede"),
    ("User works at Acme", "User got a job at Microsoft", {"DELETE"}, "supersede"),
    ("User lives in Berlin", "User relocated to Lisbon", {"DELETE"}, "supersede"),
    ("User lives in Berlin", "User just moved into a new place in Tokyo", {"DELETE"}, "supersede"),
    ("User lives in Berlin", "User is settling into life in Madrid", {"DELETE"}, "supersede"),
    ("User is married to Sam", "Sam is the user's ex now", {"DELETE"}, "supersede"),
    ("User is vegetarian", "User has started eating chicken again", {"DELETE"}, "supersede"),
    # --- direct supersede control (should pass either way) ---
    ("User works at Acme", "User now works at Netflix", {"DELETE"}, "direct"),
    # --- must NOT over-delete (guard against thinking becoming trigger-happy) ---
    ("User works at Acme", "User got promoted to senior engineer at Acme", {"UPDATE", "DELETE"}, "refine"),
    ("User lives in Berlin", "User loves Berlin's winters", {"ADD", "NOOP"}, "keep"),
    ("User works at Acme", "User enjoys hiking on weekends", {"ADD"}, "unrelated"),
]


def decide(existing, new, think):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": DECISION_SYSTEM},
            {"role": "user", "content": f"NEW fact: {new}\n\nEXISTING memories:\n- id=m1 :: {existing}"},
        ],
        "stream": False,
        "think": think,
        "format": "json",
        "options": {"num_predict": 1500 if think else 300, "temperature": 0},
    }
    req = urllib.request.Request(URL + "/api/chat", data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    if KEY:
        req.add_header("Authorization", f"Bearer {KEY}")
    with urllib.request.urlopen(req, timeout=300, context=_SSL) as r:
        msg = (json.loads(r.read().decode()).get("message") or {})
    content = (msg.get("content") or "").strip()
    # gemma wraps JSON in ```json fences even with format=json (prod uses parse_json_lenient).
    if content.startswith("```"):
        content = content.split("```")[1].removeprefix("json").strip()
    try:
        return (json.loads(content).get("operation") or "?").upper()
    except Exception:
        return "PARSE_ERR"


def run(think):
    label = "THINK ON " if think else "THINK OFF"
    print(f"\n=== {label} · {MODEL} ===")
    ok = 0
    for existing, new, accept, kind in CASES:
        op = decide(existing, new, think)
        good = op in accept
        ok += good
        print(f"  [{'✓' if good else '✗'}] {kind:<9} {new[:42]:<44} -> {op:<8} (want {'/'.join(sorted(accept))})")
    print(f"  → {ok}/{len(CASES)} correct")
    return ok


def main():
    print(f"Reconcile-decision thinking A/B · {len(CASES)} cases ({sum(1 for c in CASES if c[3]=='supersede')} indirect supersede)")
    off = run(False)
    on = run(True)
    print(f"\nSUMMARY  think-off {off}/{len(CASES)}  ·  think-on {on}/{len(CASES)}  ·  delta {on-off:+d}")


if __name__ == "__main__":
    main()
