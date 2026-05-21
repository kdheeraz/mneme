"""Memory consolidation: find near-duplicates within the same (agent_id, user_id)
scope and supersede the losers. Optionally LLM-merge content into the kept memory.
Also supports a half-life-based decay pass on `importance`."""
from __future__ import annotations
from datetime import datetime, timezone
import math
from typing import List, Tuple, Dict, Optional
from uuid import UUID

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from .models import Memory, Tenant, Agent
from .embeddings import embed_for_agent
from .llm import merge_memories


# ---- Pair finding ----

# We grab candidate pairs via SQL using pgvector's `<=>` cosine distance,
# scoped by (agent_id, user_id). NULL user_id buckets together via COALESCE.
_PAIR_SQL = """
WITH live AS (
  SELECT id, agent_id, user_id, content, embedding, created_at,
         importance, access_count
  FROM memories
  WHERE tenant_id = :tenant_id AND superseded_by_id IS NULL
)
SELECT a.id AS a_id, b.id AS b_id,
       1 - (a.embedding <=> b.embedding) AS sim
FROM live a
JOIN live b
  ON a.id < b.id
 AND a.agent_id IS NOT DISTINCT FROM b.agent_id
 AND a.user_id IS NOT DISTINCT FROM b.user_id
WHERE (1 - (a.embedding <=> b.embedding)) >= :threshold
ORDER BY sim DESC
LIMIT 500
"""


def find_pairs(db: Session, tenant: Tenant, threshold: float) -> List[Tuple[UUID, UUID, float]]:
    rows = db.execute(sql_text(_PAIR_SQL), {"tenant_id": str(tenant.id), "threshold": float(threshold)}).all()
    return [(r[0], r[1], float(r[2])) for r in rows]


# ---- Winner selection ----

def _pick_winner(a: Memory, b: Memory) -> Tuple[Memory, Memory]:
    """Higher access_count wins; tie → higher importance; tie → newer."""
    if a.access_count != b.access_count:
        return (a, b) if a.access_count > b.access_count else (b, a)
    if (a.importance or 0) != (b.importance or 0):
        return (a, b) if (a.importance or 0) > (b.importance or 0) else (b, a)
    return (a, b) if a.created_at >= b.created_at else (b, a)


# ---- Decay ----

def apply_decay(db: Session, tenant: Tenant, half_life_days: float) -> int:
    """Multiplicative half-life decay on importance.

    importance *= 0.5 ** (days_since_created / half_life_days)
    Clamped to [0, 1]. Returns rows updated."""
    if half_life_days <= 0:
        return 0
    # We compute decay in SQL for speed.
    sql = """
    UPDATE memories
    SET importance = LEAST(1.0, GREATEST(0.0,
        importance * power(0.5, EXTRACT(EPOCH FROM (now() - created_at)) / (:hl * 86400.0))
    ))
    WHERE tenant_id = :tenant AND superseded_by_id IS NULL
    """
    res = db.execute(sql_text(sql), {"tenant": str(tenant.id), "hl": float(half_life_days)})
    return res.rowcount or 0


# ---- Main entry point ----

def consolidate(
    db: Session,
    tenant: Tenant,
    similarity_threshold: float = 0.92,
    use_llm_merge: bool = False,
    decay_half_life_days: Optional[float] = None,
    dry_run: bool = False,
) -> Dict:
    pairs = find_pairs(db, tenant, similarity_threshold)

    if not pairs:
        decayed = 0 if dry_run else apply_decay(db, tenant, decay_half_life_days or 0)
        if not dry_run:
            db.commit()
        return {"pairs_found": 0, "merges_performed": 0, "decayed": decayed, "details": []}

    # Greedy: process highest-similarity first; skip if either memory was already touched.
    touched: set = set()
    details: List[Dict] = []
    merges_performed = 0

    # Hydrate all involved Memory rows once.
    ids = {p[0] for p in pairs} | {p[1] for p in pairs}
    mems: Dict[UUID, Memory] = {
        m.id: m for m in db.query(Memory).filter(Memory.id.in_(ids)).all()
    }
    # Agents cache (for LLM merge / re-embedding)
    agents_cache: Dict[str, Optional[Agent]] = {}

    def agent_for(slug: Optional[str]) -> Optional[Agent]:
        if not slug:
            return None
        if slug in agents_cache:
            return agents_cache[slug]
        ag = db.query(Agent).filter(Agent.tenant_id == tenant.id, Agent.slug == slug).first()
        agents_cache[slug] = ag
        return ag

    now = datetime.now(timezone.utc)

    for a_id, b_id, sim in pairs:
        if a_id in touched or b_id in touched:
            continue
        a = mems.get(a_id)
        b = mems.get(b_id)
        if not a or not b:
            continue
        if a.superseded_by_id or b.superseded_by_id:
            continue

        keep, lose = _pick_winner(a, b)
        merged_content: Optional[str] = None

        ag = agent_for(keep.agent_id)

        if use_llm_merge and ag and (ag.llm_provider or "none") != "none":
            try:
                merged_content = merge_memories(ag, keep.content, lose.content)
            except Exception:
                merged_content = None

        if not dry_run:
            if merged_content and merged_content != keep.content:
                keep.content = merged_content
                try:
                    keep.embedding = embed_for_agent(merged_content, ag, tenant.embedding_dim)
                except Exception:
                    # If re-embedding fails (rare), keep old embedding rather than abort.
                    pass
            lose.superseded_by_id = keep.id
            lose.superseded_at = now
            merges_performed += 1

        touched.add(a_id)
        touched.add(b_id)
        details.append({
            "kept_id": str(keep.id),
            "kept_content": keep.content,
            "superseded_id": str(lose.id),
            "superseded_content": lose.content,
            "similarity": round(sim, 4),
            "merged_content": merged_content,
        })

    decayed = 0
    if not dry_run and decay_half_life_days:
        decayed = apply_decay(db, tenant, decay_half_life_days)

    if not dry_run:
        db.commit()

    return {
        "pairs_found": len(pairs),
        "merges_performed": merges_performed,
        "decayed": decayed,
        "details": details,
    }
