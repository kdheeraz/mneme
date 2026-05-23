from datetime import datetime
from sqlalchemy import (
    Column, String, Text, DateTime, ForeignKey, Float, JSON, Integer, Index, Boolean,
    UniqueConstraint, Computed, func,
)
from sqlalchemy.dialects.postgresql import UUID, TSVECTOR
from pgvector.sqlalchemy import Vector
import uuid

from .db import Base
from .config import settings


def _uuid():
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(120))
    created_at = Column(DateTime, server_default=func.now())


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name = Column(String(120), nullable=False)
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    embedding_dim = Column(Integer, default=lambda: settings.embedding_dim, nullable=False)
    plan = Column(String(32), default="free")
    # Razorpay billing
    razorpay_customer_id = Column(String(64), nullable=True)
    razorpay_subscription_id = Column(String(64), nullable=True)
    subscription_status = Column(String(32), nullable=True)  # created/authenticated/active/halted/cancelled
    created_at = Column(DateTime, server_default=func.now())


class RazorpayPlan(Base):
    """Caches the Razorpay plan_id for each of our plan tiers so we don't recreate them."""
    __tablename__ = "razorpay_plans"
    key = Column(String(32), primary_key=True)        # "pro" | "team"
    razorpay_plan_id = Column(String(64), nullable=False)
    amount = Column(Integer, nullable=False)          # paise
    created_at = Column(DateTime, server_default=func.now())


class Agent(Base):
    """First-class agent. Owns its own LLM + embedding config + API keys."""
    __tablename__ = "agents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    slug = Column(String(80), nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(Text)

    # LLM config (used for memory extraction, summarization, consolidation)
    llm_provider = Column(String(32), default="none")  # "none" | "openai" | "anthropic" | "ollama"
    llm_model = Column(String(80), default="gpt-4o-mini")
    llm_api_key_enc = Column(Text)  # Fernet-encrypted
    llm_base_url = Column(String(255))  # for Ollama / OpenAI-compatible servers
    # AWS Bedrock (llm_provider == "bedrock"): region + creds. Keys Fernet-encrypted.
    # If the keys are blank, the Bedrock client falls back to the container's ambient
    # AWS credentials (instance role / env).
    aws_region = Column(String(40))
    aws_access_key_enc = Column(Text)
    aws_secret_key_enc = Column(Text)

    # Embedding config (must match tenant embedding_dim)
    embedding_provider = Column(String(32), default="fake")  # "fake" | "openai" | "ollama"
    embedding_model = Column(String(80), default="text-embedding-3-small")
    embedding_api_key_enc = Column(Text)
    embedding_base_url = Column(String(255))  # for Ollama / custom endpoints

    # Reranker config (cross-encoder; runs after RRF blend)
    rerank_provider = Column(String(32), default="none")  # "none" | "cohere" | "voyage" | "jina"
    rerank_model = Column(String(80), default="rerank-english-v3.0")
    rerank_api_key_enc = Column(Text)

    # Behavior flags
    auto_extract = Column(Boolean, default=False)  # if true, LLM extracts atomic memories from raw input
    # Mem0-style write-time reconciliation: on each write, LLM decides ADD/UPDATE/DELETE/NOOP
    reconcile = Column(Boolean, default=False)
    # Graph memory: on each write, LLM extracts entities + relationships into the graph store
    graph_enabled = Column(Boolean, default=False)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_agents_tenant_slug"),
    )


class ApiKey(Base):
    """API key. Either tenant-scoped (agent_slug = NULL) or agent-scoped."""
    __tablename__ = "api_keys"
    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_slug = Column(String(80), nullable=True, index=True)  # null => tenant-wide
    key = Column(String(80), unique=True, nullable=False, index=True)
    label = Column(String(120))
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class Memory(Base):
    __tablename__ = "memories"
    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(120), index=True)  # = agents.slug
    user_id = Column(String(120), index=True)
    session_id = Column(String(120), index=True)
    content = Column(Text, nullable=False)
    kind = Column(String(32), default="semantic")  # semantic | episodic | procedural
    # private = only the owning agent can read it; shared = any agent in the tenant can read it
    scope = Column(String(16), default="private", index=True)
    meta = Column(JSON, default=dict)
    embedding = Column(Vector(settings.embedding_dim))
    # Lexical search column — Postgres auto-maintains it from `content`.
    content_tsv = Column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
    )
    importance = Column(Float, default=0.5)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_accessed_at = Column(DateTime, server_default=func.now())
    access_count = Column(Integer, default=0)
    # Consolidation: when set, this memory has been merged into another and is hidden from search.
    superseded_by_id = Column(UUID(as_uuid=True), ForeignKey("memories.id", ondelete="SET NULL"), nullable=True, index=True)
    superseded_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_memories_tenant_agent", "tenant_id", "agent_id"),
        Index("ix_memories_tenant_user", "tenant_id", "user_id"),
        Index("ix_memories_content_tsv", "content_tsv", postgresql_using="gin"),
    )


class GraphEntity(Base):
    """A node in the knowledge graph (person, org, technology, concept, ...)."""
    __tablename__ = "graph_entities"
    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(120), index=True)
    name = Column(String(200), nullable=False)            # canonical display name
    norm_name = Column(String(200), nullable=False, index=True)  # lowercased for dedup
    type = Column(String(40), default="other")            # person/org/place/technology/product/concept/event/other
    mention_count = Column(Integer, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_id", "norm_name", "type", name="uq_graph_entity"),
    )


class GraphRelation(Base):
    """A directed edge: subject --predicate--> object."""
    __tablename__ = "graph_relations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(120), index=True)
    subject_id = Column(UUID(as_uuid=True), ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    predicate = Column(String(80), nullable=False)
    object_id = Column(UUID(as_uuid=True), ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    source_memory_id = Column(UUID(as_uuid=True), ForeignKey("memories.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "subject_id", "predicate", "object_id", name="uq_graph_relation"),
    )


class Trace(Base):
    __tablename__ = "traces"
    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(120), index=True)
    user_id = Column(String(120))
    session_id = Column(String(120))
    op = Column(String(32))
    query = Column(Text)
    results = Column(JSON)
    latency_ms = Column(Integer)
    created_at = Column(DateTime, server_default=func.now(), index=True)
