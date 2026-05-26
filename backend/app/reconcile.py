"""Mem0-style write-time reconciliation.

On each write, find near-duplicate existing memories in the same scope and let the
agent's LLM decide a single operation:

  ADD    – genuinely new info → insert
  NOOP   – already captured → store nothing
  UPDATE – refines one existing memory → rewrite that memory in place
  DELETE – contradicts/obsoletes one existing memory → supersede it, insert the new fact

Safe default is always ADD — we never silently drop information on parse/LLM failure.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Memory, Agent, Tenant
from .embeddings import embed_for_agent
from .llm import chat
from .jsonutil import parse_json_lenient


# Above this candidate-similarity, ALWAYS consult the LLM (likely dup / UPDATE / DELETE).
# Below it, only consult the LLM when the new fact carries an explicit change signal —
# otherwise just ADD. This kills the per-fact LLM cascade that made rich-extraction ingests
# (10-15 facts each) take 25-60s. The threshold is below the ~0.77 worst-case cited in the
# sim_threshold comment below, so genuine contradictions phrased differently still trigger.
HIGH_SIM_GATE = 0.75
CHANGE_SIGNAL_WORDS = (
    " left ", " moved ", " no longer ", " now ", " switched ", " previously ",
    " used to ", " instead of ", " no more ", " changed ", " updated ", " as of ",
    " formerly ", " ex-", " quit ", " stopped ", " anymore ", " update: ",
)


def _has_change_signal(text: str) -> bool:
    t = " " + (text or "").lower() + " "
    return any(sig in t for sig in CHANGE_SIGNAL_WORDS)


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


def _find_candidates(
    db: Session, tenant: Tenant, agent_slug: Optional[str], user_id: Optional[str],
    qvec, threshold: float, k: int = 8,
) -> List[Tuple[Memory, float]]:
    stmt = select(
        Memory, (1 - Memory.embedding.cosine_distance(qvec)).label("sim")
    ).where(Memory.tenant_id == tenant.id, Memory.superseded_by_id.is_(None))
    if agent_slug:
        stmt = stmt.where(Memory.agent_id == agent_slug)
    if user_id:
        stmt = stmt.where(Memory.user_id == user_id)
    stmt = stmt.order_by(Memory.embedding.cosine_distance(qvec)).limit(k)
    rows = db.execute(stmt).all()
    return [(m, float(s)) for m, s in rows if float(s) >= threshold]


def _decide(agent: Agent, new_content: str, candidates: List[Tuple[Memory, float]]) -> dict:
    cand_text = "\n".join(f"- id={m.id} :: {m.content}" for m, _ in candidates)
    raw = chat(
        agent,
        [
            {"role": "system", "content": DECISION_SYSTEM},
            {"role": "user", "content": f"NEW fact: {new_content}\n\nEXISTING memories:\n{cand_text}"},
        ],
        max_tokens=300,
        json_mode=True,
    )
    return parse_json_lenient(raw)


def _insert(db, tenant, agent_slug, content, kind, scope, user_id, session_id, importance, meta, vec) -> Memory:
    m = Memory(
        tenant_id=tenant.id, agent_id=agent_slug, user_id=user_id, session_id=session_id,
        content=content, kind=kind, scope=scope, meta=meta or {"source": "reconcile"},
        importance=importance, embedding=vec,
    )
    db.add(m)
    db.flush()  # populate m.id for DELETE linkage; endpoint commits
    return m


def reconcile_write(
    db: Session, tenant: Tenant, agent: Agent, *,
    content: str, kind: str, scope: str,
    user_id: Optional[str], session_id: Optional[str],
    importance: float, meta: Optional[dict],
    # Raw source text that produced `content` (e.g. the ingest transcript). Used only by
    # the change-signal pre-filter — extraction strips words like 'moved/now/no longer'
    # when normalizing to present-tense, so we'd miss them if we only inspected `content`.
    source_text: Optional[str] = None,
    # Candidate floor for what the LLM gets to reconcile against. Kept moderate (not 0.80):
    # genuinely-contradictory facts can be only ~0.77 similar when phrased differently
    # (e.g. "moved to Berlin" vs "lives in Bangalore"), and the LLM is the real gate —
    # it returns ADD/NOOP for anything that isn't actually a match.
    sim_threshold: float = 0.60,
) -> Tuple[Optional[Memory], str]:
    """Returns (resulting_memory, operation). For NOOP, resulting_memory is the matched
    existing memory (so callers always get something back)."""
    vec = embed_for_agent(content, agent, tenant.embedding_dim)
    agent_slug = agent.slug if agent else None

    candidates = _find_candidates(db, tenant, agent_slug, user_id, vec, sim_threshold)

    # Nothing similar, or no LLM to reason with → ADD.
    if not candidates or (agent.llm_provider or "none") == "none":
        return _insert(db, tenant, agent_slug, content, kind, scope, user_id, session_id, importance, meta, vec), "ADD"

    # Fast path: only pay the LLM when reconciliation is actually likely.
    # (a) a candidate is very similar (likely duplicate / UPDATE / DELETE), or
    # (b) the new fact carries an explicit change signal ('moved', 'no longer', 'now', ...).
    # Otherwise just ADD. This cuts per-ingest LLM calls from O(facts) to ~the few that
    # genuinely need a decision, without weakening contradiction handling.
    max_sim = max(s for _, s in candidates)
    if max_sim < HIGH_SIM_GATE and not _has_change_signal(content) and not _has_change_signal(source_text):
        return _insert(db, tenant, agent_slug, content, kind, scope, user_id, session_id, importance, meta, vec), "ADD"

    try:
        decision = _decide(agent, content, candidates)
    except Exception:
        return _insert(db, tenant, agent_slug, content, kind, scope, user_id, session_id, importance, meta, vec), "ADD"

    op = (decision.get("operation") or "ADD").upper()
    target_id = decision.get("target_id")
    final_content = (decision.get("content") or content).strip()
    target = next((m for m, _ in candidates if str(m.id) == str(target_id)), None)
    now = datetime.now(timezone.utc)

    if op == "NOOP":
        return (target or candidates[0][0]), "NOOP"

    if op == "UPDATE" and target:
        target.content = final_content
        target.embedding = embed_for_agent(final_content, agent, tenant.embedding_dim)
        target.updated_at = now
        return target, "UPDATE"

    if op == "DELETE" and target:
        new_vec = embed_for_agent(final_content, agent, tenant.embedding_dim) if final_content != content else vec
        m = _insert(db, tenant, agent_slug, final_content, kind, scope, user_id, session_id, importance, meta, new_vec)
        target.superseded_by_id = m.id
        target.superseded_at = now
        return m, "DELETE"

    # default / unrecognized → ADD (never lose info)
    return _insert(db, tenant, agent_slug, content, kind, scope, user_id, session_id, importance, meta, vec), "ADD"
