export type MemoryKind = "semantic" | "episodic" | "procedural";
export type Scope = "private" | "shared";
export type SearchMode = "vector" | "lexical" | "hybrid";

export interface Memory {
  id: string;
  tenant_id: string;
  agent_id: string | null;
  user_id: string | null;
  session_id: string | null;
  content: string;
  kind: MemoryKind;
  scope: Scope;
  meta: Record<string, unknown>;
  importance: number;
  created_at: string;
  updated_at: string;
  last_accessed_at: string;
  access_count: number;
}

export interface AddOptions {
  agentId?: string;
  userId?: string;
  sessionId?: string;
  kind?: MemoryKind;
  scope?: Scope;
  meta?: Record<string, unknown>;
  importance?: number;
}

export interface IngestMessage {
  role: string;
  content: string;
}

export interface IngestOptions {
  messages?: IngestMessage[];
  text?: string;
  context?: string;
  agentId?: string;
  userId?: string;
  sessionId?: string;
  scope?: Scope;
  persist?: boolean;
}

export interface IngestResult {
  extracted: number;
  persisted: number;
  memories: Memory[];
  raw_llm_response: string | null;
  trace_id: string | null;
  latency_ms: number;
}

export interface SearchOptions {
  agentId?: string;
  userId?: string;
  sessionId?: string;
  kind?: MemoryKind;
  limit?: number;
  mode?: SearchMode;
  recencyWeight?: number;
  rrfK?: number;
  candidates?: number;
  rerank?: boolean;
  rerankTopK?: number;
  rewrite?: boolean;
  useGraph?: boolean;
  crossAgent?: boolean;
}

export interface SearchHit {
  memory: Memory;
  similarity: number;
  lexical_score: number;
  graph_score: number;
  vector_rank: number | null;
  lexical_rank: number | null;
  graph_rank: number | null;
  rrf_score: number;
  rerank_score: number | null;
  recency_boost: number;
  final_score: number;
}

export interface SearchResult {
  trace_id: string;
  hits: SearchHit[];
  latency_ms: number;
  original_query: string | null;
  rewritten_query: string | null;
  rewrite_error: string | null;
}

export interface ListFilters {
  agentId?: string;
  userId?: string;
  sessionId?: string;
  kind?: MemoryKind;
  limit?: number;
  offset?: number;
}

export interface UpdatePatch {
  content?: string;
  meta?: Record<string, unknown>;
  importance?: number;
}

export interface Trace {
  id: string;
  agent_id: string | null;
  user_id: string | null;
  session_id: string | null;
  op: string;
  query: string | null;
  results: unknown;
  latency_ms: number | null;
  created_at: string;
}

export interface TraceFilters {
  agentId?: string;
  op?: string;
  limit?: number;
}

export interface Stats {
  total_memories: number;
  total_traces: number;
  total_agents: number;
  memories_by_kind: Record<string, number>;
  memories_by_agent: { agent_id: string; count: number }[];
  recent_ops_24h: number;
}

export interface GraphEntity {
  id: string;
  name: string;
  type: string;
  mention_count: number;
}

export interface GraphRelation {
  id: string;
  subject_id: string;
  predicate: string;
  object_id: string;
}

export interface Graph {
  entities: GraphEntity[];
  relations: GraphRelation[];
}

export interface MnemeOptions {
  apiKey: string;
  baseUrl?: string;
  timeoutMs?: number;
  fetch?: typeof fetch;
}
