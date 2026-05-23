import type {
  Memory, AddOptions, IngestOptions, IngestResult,
  SearchOptions, SearchResult, ListFilters, UpdatePatch,
  Trace, TraceFilters, Stats, MnemeOptions, Graph,
} from "./types.js";

export class MnemeError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.name = "MnemeError";
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Mneme — memory for LLM agents.
 *
 * ```ts
 * const m = new Mneme({ apiKey: "mneme_sk_..." });
 * await m.add("User prefers PyTorch", { userId: "user_42" });
 * const res = await m.search("which framework?", { userId: "user_42" });
 * ```
 */
export class Mneme {
  private apiKey: string;
  private baseUrl: string;
  private timeoutMs: number;
  private _fetch: typeof fetch;

  constructor(opts: MnemeOptions) {
    if (!opts?.apiKey) throw new Error("apiKey is required");
    this.apiKey = opts.apiKey;
    this.baseUrl = (opts.baseUrl ?? "http://localhost:8000").replace(/\/+$/, "");
    this.timeoutMs = opts.timeoutMs ?? 30_000;
    this._fetch = opts.fetch ?? globalThis.fetch;
    if (!this._fetch) {
      throw new Error("global fetch not found — use Node 18+ or pass opts.fetch");
    }
  }

  private async req<T>(method: string, path: string, body?: unknown, query?: Record<string, unknown>): Promise<T> {
    let url = `${this.baseUrl}${path}`;
    if (query) {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(query)) {
        if (v !== undefined && v !== null) qs.set(k, String(v));
      }
      const s = qs.toString();
      if (s) url += `?${s}`;
    }

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.timeoutMs);
    try {
      const res = await this._fetch(url, {
        method,
        headers: { "Content-Type": "application/json", "X-API-Key": this.apiKey },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: ctrl.signal,
      });
      const text = await res.text();
      const data = text ? JSON.parse(text) : null;
      if (!res.ok) {
        throw new MnemeError(res.status, (data && (data.detail ?? data)) ?? res.statusText);
      }
      return data as T;
    } finally {
      clearTimeout(timer);
    }
  }

  // ---- memories ----

  add(content: string, opts: AddOptions = {}): Promise<Memory> {
    return this.req<Memory>("POST", "/v1/memories", {
      content,
      agent_id: opts.agentId,
      user_id: opts.userId,
      session_id: opts.sessionId,
      kind: opts.kind ?? "semantic",
      scope: opts.scope ?? "private",
      meta: opts.meta ?? {},
      importance: opts.importance ?? 0.5,
    });
  }

  ingest(opts: IngestOptions): Promise<IngestResult> {
    return this.req<IngestResult>("POST", "/v1/memories/ingest", {
      messages: opts.messages,
      text: opts.text,
      context: opts.context,
      agent_id: opts.agentId,
      user_id: opts.userId,
      session_id: opts.sessionId,
      scope: opts.scope ?? "private",
      persist: opts.persist ?? true,
    });
  }

  search(query: string, opts: SearchOptions = {}): Promise<SearchResult> {
    return this.req<SearchResult>("POST", "/v1/memories/search", {
      query,
      agent_id: opts.agentId,
      user_id: opts.userId,
      session_id: opts.sessionId,
      kind: opts.kind,
      limit: opts.limit ?? 10,
      mode: opts.mode ?? "hybrid",
      recency_weight: opts.recencyWeight ?? 0.15,
      rrf_k: opts.rrfK ?? 60,
      candidates: opts.candidates ?? 30,
      rerank: opts.rerank ?? false,
      rerank_top_k: opts.rerankTopK ?? 30,
      rewrite: opts.rewrite ?? false,
      use_graph: opts.useGraph ?? false,
      cross_agent: opts.crossAgent ?? false,
    });
  }

  list(filters: ListFilters = {}): Promise<Memory[]> {
    return this.req<Memory[]>("GET", "/v1/memories", undefined, {
      agent_id: filters.agentId,
      user_id: filters.userId,
      session_id: filters.sessionId,
      kind: filters.kind,
      limit: filters.limit,
      offset: filters.offset,
    });
  }

  get(memoryId: string): Promise<Memory> {
    return this.req<Memory>("GET", `/v1/memories/${memoryId}`);
  }

  update(memoryId: string, patch: UpdatePatch): Promise<Memory> {
    return this.req<Memory>("PATCH", `/v1/memories/${memoryId}`, patch);
  }

  async delete(memoryId: string): Promise<void> {
    await this.req<unknown>("DELETE", `/v1/memories/${memoryId}`);
  }

  // ---- observability ----

  traces(filters: TraceFilters = {}): Promise<Trace[]> {
    return this.req<Trace[]>("GET", "/v1/traces", undefined, {
      agent_id: filters.agentId,
      op: filters.op,
      limit: filters.limit,
    });
  }

  trace(traceId: string): Promise<Trace> {
    return this.req<Trace>("GET", `/v1/traces/${traceId}`);
  }

  stats(): Promise<Stats> {
    return this.req<Stats>("GET", "/v1/stats");
  }

  // ---- graph memory ----

  graph(opts: { agentId?: string; limit?: number } = {}): Promise<Graph> {
    return this.req<Graph>("GET", "/v1/graph", undefined, {
      agent_id: opts.agentId,
      limit: opts.limit ?? 300,
    });
  }

  rebuildGraph(opts: { agentId?: string } = {}): Promise<Record<string, unknown>> {
    return this.req("POST", "/v1/graph/rebuild", undefined, { agent_id: opts.agentId });
  }
}
