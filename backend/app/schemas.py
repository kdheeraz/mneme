from datetime import datetime
from typing import Optional, List, Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field, EmailStr


# -------- Auth --------

class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: Optional[str] = None
    tenant_name: Optional[str] = None  # defaults to "{name}'s workspace"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"
    tenant: "TenantOut"


class UserOut(BaseModel):
    id: UUID
    email: str
    name: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# -------- Tenant --------

class TenantIn(BaseModel):
    name: str


class TenantOut(BaseModel):
    id: UUID
    name: str
    embedding_dim: int
    plan: str
    created_at: datetime

    class Config:
        from_attributes = True


# -------- Agent --------

LLMProvider = Literal["none", "openai", "anthropic", "ollama"]
EmbProvider = Literal["fake", "openai", "ollama"]
RerankProvider = Literal["none", "cohere", "voyage", "jina"]


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: Optional[str] = None
    description: Optional[str] = None

    llm_provider: LLMProvider = "none"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None

    embedding_provider: EmbProvider = "fake"
    embedding_model: str = "text-embedding-3-small"
    embedding_api_key: Optional[str] = None
    embedding_base_url: Optional[str] = None

    rerank_provider: RerankProvider = "none"
    rerank_model: str = "rerank-english-v3.0"
    rerank_api_key: Optional[str] = None

    auto_extract: bool = False


class AgentPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    llm_provider: Optional[LLMProvider] = None
    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    embedding_provider: Optional[EmbProvider] = None
    embedding_model: Optional[str] = None
    embedding_api_key: Optional[str] = None
    embedding_base_url: Optional[str] = None
    rerank_provider: Optional[RerankProvider] = None
    rerank_model: Optional[str] = None
    rerank_api_key: Optional[str] = None
    auto_extract: Optional[bool] = None


class AgentOut(BaseModel):
    id: UUID
    tenant_id: UUID
    slug: str
    name: str
    description: Optional[str]
    llm_provider: str
    llm_model: str
    llm_api_key_set: bool
    llm_base_url: Optional[str]
    embedding_provider: str
    embedding_model: str
    embedding_api_key_set: bool
    embedding_base_url: Optional[str]
    rerank_provider: str
    rerank_model: str
    rerank_api_key_set: bool
    auto_extract: bool
    memory_count: int = 0
    created_at: datetime
    updated_at: datetime


class AgentTestOut(BaseModel):
    embedding_ok: bool
    embedding_dim: Optional[int] = None
    embedding_error: Optional[str] = None
    llm_ok: bool
    llm_sample: Optional[str] = None
    llm_error: Optional[str] = None


# -------- API keys --------

class ApiKeyIn(BaseModel):
    label: Optional[str] = "default"
    agent_slug: Optional[str] = None  # null = tenant-wide


class ApiKeyOut(BaseModel):
    id: UUID
    tenant_id: UUID
    agent_slug: Optional[str]
    key: str
    label: Optional[str]
    last_used_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# -------- Memories (unchanged from v1) --------

class MemoryIn(BaseModel):
    content: str
    agent_id: Optional[str] = None  # ignored if key is agent-scoped
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    kind: Literal["semantic", "episodic", "procedural"] = "semantic"
    meta: dict = Field(default_factory=dict)
    importance: float = 0.5


class IngestMessage(BaseModel):
    role: str = "user"
    content: str


class IngestIn(BaseModel):
    """Auto-extract memories from a conversation or text blob."""
    messages: Optional[List[IngestMessage]] = None
    text: Optional[str] = None
    context: Optional[str] = None
    agent_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    importance: float = 0.5
    persist: bool = True  # if false, run extraction but don't write to DB (dry-run)


class IngestOut(BaseModel):
    extracted: int
    persisted: int
    memories: List["MemoryOut"]
    raw_llm_response: Optional[str] = None
    trace_id: Optional[UUID] = None
    latency_ms: int


class MemoryOut(BaseModel):
    id: UUID
    tenant_id: UUID
    agent_id: Optional[str]
    user_id: Optional[str]
    session_id: Optional[str]
    content: str
    kind: str
    meta: dict
    importance: float
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime
    access_count: int

    class Config:
        from_attributes = True


class MemoryPatch(BaseModel):
    content: Optional[str] = None
    meta: Optional[dict] = None
    importance: Optional[float] = None


SearchMode = Literal["vector", "lexical", "hybrid"]


class SearchIn(BaseModel):
    query: str
    agent_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    kind: Optional[Literal["semantic", "episodic", "procedural"]] = None
    limit: int = 10
    recency_weight: float = 0.15
    cross_agent: bool = False
    mode: SearchMode = "hybrid"
    rrf_k: int = 60
    candidates: int = 30
    # Reranker: when true, take top `rerank_top_k` after RRF and reorder via the agent's reranker
    rerank: bool = False
    rerank_top_k: int = 30
    # Query rewriting via the agent's LLM (expand short queries with synonyms / context)
    rewrite: bool = False


class SearchHit(BaseModel):
    memory: MemoryOut
    similarity: float = 0.0
    lexical_score: float = 0.0
    vector_rank: Optional[int] = None
    lexical_rank: Optional[int] = None
    rrf_score: float = 0.0
    rerank_score: Optional[float] = None
    recency_boost: float = 0.0
    final_score: float = 0.0


class SearchOut(BaseModel):
    trace_id: UUID
    hits: List[SearchHit]
    latency_ms: int
    original_query: Optional[str] = None
    rewritten_query: Optional[str] = None
    rewrite_error: Optional[str] = None


class TraceOut(BaseModel):
    id: UUID
    agent_id: Optional[str]
    user_id: Optional[str]
    session_id: Optional[str]
    op: str
    query: Optional[str]
    results: Any
    latency_ms: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


class StatsOut(BaseModel):
    total_memories: int
    total_traces: int
    total_agents: int
    memories_by_kind: dict
    memories_by_agent: List[dict]
    recent_ops_24h: int


class ConsolidateIn(BaseModel):
    similarity_threshold: float = 0.92
    use_llm_merge: bool = False
    decay_half_life_days: Optional[float] = None  # if set, importance decays with this half-life
    dry_run: bool = False


class ConsolidatePair(BaseModel):
    kept_id: UUID
    kept_content: str
    superseded_id: UUID
    superseded_content: str
    similarity: float
    merged_content: Optional[str] = None  # when use_llm_merge produced new content


class ConsolidateOut(BaseModel):
    pairs_found: int
    merges_performed: int
    decayed_count: int
    pairs: List[ConsolidatePair]
    latency_ms: int


# resolve forward refs
TokenOut.model_rebuild()
IngestOut.model_rebuild()
