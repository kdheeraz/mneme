"""Graph memory (Mem0g-style): extract entities + relationships from text using the
agent's LLM and upsert them into the graph store (Postgres tables, no extra infra).

Entities are deduplicated within (tenant, agent) by normalized name + type. Relations
are deduplicated by (subject, predicate, object)."""
from __future__ import annotations
from typing import Optional, List, Dict, Tuple

from sqlalchemy.orm import Session

from .models import Agent, Tenant, GraphEntity, GraphRelation
from .llm import chat
from .jsonutil import parse_json_lenient


GRAPH_SYSTEM = (
    "Extract a knowledge graph from the text. Identify entities and the relationships "
    "between them.\n"
    "- entities: concrete things — people, organizations, places, technologies, products, "
    "concepts, events.\n"
    "- For each entity: a canonical `name` and a `type` "
    "(person|org|place|technology|product|concept|event|other).\n"
    "- relations: directed subject→predicate→object, referencing entity names. `predicate` "
    "is a short lowercase verb phrase, e.g. 'prefers', 'works_at', 'located_in', 'uses'.\n"
    "Skip pronouns; resolve 'I'/'the user' to the entity 'User'.\n"
    'Return JSON only: {"entities":[{"name":"...","type":"..."}],'
    '"relations":[{"subject":"...","predicate":"...","object":"..."}]}'
)

VALID_TYPES = {"person", "org", "place", "technology", "product", "concept", "event", "other"}


def extract_graph(agent: Agent, content: str) -> Dict[str, list]:
    """Returns {"entities": [...], "relations": [...]}. Raises if agent has no LLM."""
    if not agent or (agent.llm_provider or "none") == "none":
        raise ValueError("agent has no LLM configured for graph extraction")
    raw = chat(
        agent,
        [
            {"role": "system", "content": GRAPH_SYSTEM},
            {"role": "user", "content": content},
        ],
        max_tokens=700,
        json_mode=True,
    )
    parsed = parse_json_lenient(raw)
    entities = []
    for e in parsed.get("entities") or []:
        name = (e.get("name") or "").strip()
        if not name:
            continue
        etype = (e.get("type") or "other").strip().lower()
        if etype not in VALID_TYPES:
            etype = "other"
        entities.append({"name": name, "type": etype})
    relations = []
    for r in parsed.get("relations") or []:
        s = (r.get("subject") or "").strip()
        p = (r.get("predicate") or "").strip().lower().replace(" ", "_")
        o = (r.get("object") or "").strip()
        if s and p and o:
            relations.append({"subject": s, "predicate": p, "object": o})
    return {"entities": entities, "relations": relations}


def _upsert_entity(db: Session, tenant: Tenant, agent_slug: str, name: str, etype: str) -> GraphEntity:
    norm = name.lower().strip()
    ent = (
        db.query(GraphEntity)
        .filter(
            GraphEntity.tenant_id == tenant.id,
            GraphEntity.agent_id == agent_slug,
            GraphEntity.norm_name == norm,
            GraphEntity.type == etype,
        )
        .first()
    )
    if ent:
        ent.mention_count = (ent.mention_count or 1) + 1
        return ent
    ent = GraphEntity(
        tenant_id=tenant.id, agent_id=agent_slug, name=name, norm_name=norm, type=etype,
    )
    db.add(ent)
    db.flush()
    return ent


def upsert_graph(
    db: Session, tenant: Tenant, agent_slug: str, extracted: Dict[str, list],
    source_memory_id=None,
) -> Tuple[int, int]:
    """Returns (entities_touched, relations_added)."""
    # entity name(+type) → GraphEntity; resolve relations against best-match by name
    by_norm: Dict[str, GraphEntity] = {}
    for e in extracted["entities"]:
        ent = _upsert_entity(db, tenant, agent_slug, e["name"], e["type"])
        by_norm[e["name"].lower().strip()] = ent

    def resolve(name: str) -> GraphEntity:
        key = name.lower().strip()
        if key in by_norm:
            return by_norm[key]
        # relation referenced an entity not in the entities list — create as 'other'
        ent = _upsert_entity(db, tenant, agent_slug, name, "other")
        by_norm[key] = ent
        return ent

    rel_added = 0
    for r in extracted["relations"]:
        subj = resolve(r["subject"])
        obj = resolve(r["object"])
        if subj.id == obj.id:
            continue
        exists = (
            db.query(GraphRelation)
            .filter(
                GraphRelation.tenant_id == tenant.id,
                GraphRelation.subject_id == subj.id,
                GraphRelation.predicate == r["predicate"],
                GraphRelation.object_id == obj.id,
            )
            .first()
        )
        if exists:
            continue
        db.add(GraphRelation(
            tenant_id=tenant.id, agent_id=agent_slug,
            subject_id=subj.id, predicate=r["predicate"], object_id=obj.id,
            source_memory_id=source_memory_id,
        ))
        rel_added += 1

    return len(by_norm), rel_added


def ingest_to_graph(db: Session, tenant: Tenant, agent: Agent, content: str, source_memory_id=None) -> Tuple[int, int]:
    """Convenience: extract + upsert. Returns (entities, relations_added). Best-effort."""
    extracted = extract_graph(agent, content)
    return upsert_graph(db, tenant, agent.slug, extracted, source_memory_id)


# -------- Graph-augmented retrieval --------

from uuid import UUID
from .models import GraphEntity as _GE, GraphRelation as _GR


def _link_query_entities(db: Session, tenant: Tenant, agent_slug: Optional[str], query: str) -> List[UUID]:
    """Find graph entities mentioned in the query (name-based linking)."""
    q = " " + query.lower().strip() + " "
    tokens = {t for t in query.lower().split() if len(t) >= 4}
    eq = db.query(_GE).filter(_GE.tenant_id == tenant.id)
    if agent_slug:
        eq = eq.filter(_GE.agent_id == agent_slug)
    matched: List[UUID] = []
    for e in eq.all():
        nn = e.norm_name
        if not nn:
            continue
        if nn in q or (" " + nn + " ") in q:           # whole-name appears in query
            matched.append(e.id)
            continue
        ewords = set(nn.split())
        if ewords & tokens:                             # shares a meaningful token
            matched.append(e.id)
    return matched


def graph_candidates(
    db: Session, tenant: Tenant, agent_slug: Optional[str], query: str, limit: int = 30,
) -> List[Tuple[UUID, float]]:
    """Return [(memory_id, graph_score)] for memories connected to the query's entity
    subgraph. Score = number of relevant relations the memory contributed."""
    seed = _link_query_entities(db, tenant, agent_slug, query)
    if not seed:
        return []
    seed_set = set(seed)

    rq = db.query(_GR).filter(_GR.tenant_id == tenant.id)
    if agent_slug:
        rq = rq.filter(_GR.agent_id == agent_slug)
    rels = rq.all()

    # 1-hop expansion: entities adjacent to seed
    neighbors = set(seed_set)
    for r in rels:
        if r.subject_id in seed_set or r.object_id in seed_set:
            neighbors.add(r.subject_id)
            neighbors.add(r.object_id)

    # memories that produced relations touching the relevant subgraph
    mem_scores: dict = {}
    for r in rels:
        if r.source_memory_id and (r.subject_id in neighbors or r.object_id in neighbors):
            # weight direct seed hits higher than 1-hop
            w = 2.0 if (r.subject_id in seed_set or r.object_id in seed_set) else 1.0
            mem_scores[r.source_memory_id] = mem_scores.get(r.source_memory_id, 0.0) + w

    ranked = sorted(mem_scores.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[:limit]
