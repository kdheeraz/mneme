"use client";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// -------- storage helpers --------

const TOKEN_KEY = "mneme_token";
const APIKEY_KEY = "mneme_api_key";
const USER_KEY = "mneme_user";
const TENANT_KEY = "mneme_tenant";

export const auth = {
  setSession(data: { access_token: string; user: any; tenant: any }) {
    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    localStorage.setItem(TENANT_KEY, JSON.stringify(data.tenant));
  },
  token(): string {
    if (typeof window === "undefined") return "";
    return localStorage.getItem(TOKEN_KEY) || "";
  },
  user(): any | null {
    if (typeof window === "undefined") return null;
    const v = localStorage.getItem(USER_KEY);
    return v ? JSON.parse(v) : null;
  },
  tenant(): any | null {
    if (typeof window === "undefined") return null;
    const v = localStorage.getItem(TENANT_KEY);
    return v ? JSON.parse(v) : null;
  },
  setApiKey(k: string) {
    localStorage.setItem(APIKEY_KEY, k);
  },
  apiKey(): string {
    if (typeof window === "undefined") return "";
    return localStorage.getItem(APIKEY_KEY) || "";
  },
  clear() {
    [TOKEN_KEY, APIKEY_KEY, USER_KEY, TENANT_KEY].forEach((k) => localStorage.removeItem(k));
  },
};

// -------- HTTP --------

async function jreq<T>(path: string, init: RequestInit = {}, useJwt = true): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    // Bypass ngrok's free-tier browser-warning interstitial so fetches get JSON, not HTML.
    // Ignored by every other server, so it's safe to always send.
    "ngrok-skip-browser-warning": "true",
    ...((init.headers as Record<string, string>) || {}),
  };
  if (useJwt) {
    const t = auth.token();
    if (t) headers["Authorization"] = `Bearer ${t}`;
  } else {
    const k = auth.apiKey();
    if (k) headers["X-API-Key"] = k;
  }
  const r = await fetch(`${BASE}${path}`, { ...init, headers, cache: "no-store" });
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      const j = await r.json();
      msg = j.detail || JSON.stringify(j);
    } catch {
      msg = await r.text();
    }
    throw new Error(msg);
  }
  if (r.status === 204) return null as unknown as T;
  return r.json() as Promise<T>;
}

// -------- API --------

export const api = {
  // auth
  signup: (body: { email: string; password: string; name?: string; tenant_name?: string }) =>
    jreq<any>("/v1/auth/signup", { method: "POST", body: JSON.stringify(body) }, false),
  login: (body: { email: string; password: string }) =>
    jreq<any>("/v1/auth/login", { method: "POST", body: JSON.stringify(body) }, false),
  me: () => jreq<any>("/v1/auth/me"),

  // agents
  listAgents: () => jreq<any[]>("/v1/agents"),
  getAgent: (slug: string) => jreq<any>(`/v1/agents/${slug}`),
  createAgent: (body: any) => jreq<any>("/v1/agents", { method: "POST", body: JSON.stringify(body) }),
  updateAgent: (slug: string, body: any) =>
    jreq<any>(`/v1/agents/${slug}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteAgent: (slug: string) => jreq<any>(`/v1/agents/${slug}`, { method: "DELETE" }),
  testAgent: (slug: string) => jreq<any>(`/v1/agents/${slug}/test`, { method: "POST" }),

  // keys
  listKeys: (agent_slug?: string) =>
    jreq<any[]>(`/v1/keys${agent_slug ? `?agent_slug=${agent_slug}` : ""}`),
  createKey: (body: { label?: string; agent_slug?: string | null }) =>
    jreq<any>("/v1/keys", { method: "POST", body: JSON.stringify(body) }),
  deleteKey: (id: string) => jreq<any>(`/v1/keys/${id}`, { method: "DELETE" }),

  // stats + traces (JWT)
  stats: () => jreq<any>("/v1/stats"),
  listTraces: (params: Record<string, string | undefined> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v) as [string, string][]
    ).toString();
    return jreq<any[]>(`/v1/traces?${qs}`);
  },

  // memories (api-key auth)
  listMemories: (params: Record<string, string | undefined> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v) as [string, string][]
    ).toString();
    return jreq<any[]>(`/v1/memories?${qs}`, {}, false);
  },
  addMemory: (body: any) =>
    jreq<any>("/v1/memories", { method: "POST", body: JSON.stringify(body) }, false),
  deleteMemory: (id: string) => jreq<any>(`/v1/memories/${id}`, { method: "DELETE" }, false),
  searchMemories: (body: any) =>
    jreq<any>("/v1/memories/search", { method: "POST", body: JSON.stringify(body) }, false),
  ingest: (body: any) =>
    jreq<any>("/v1/memories/ingest", { method: "POST", body: JSON.stringify(body) }, false),
  consolidate: (body: any) =>
    jreq<any>("/v1/admin/consolidate", { method: "POST", body: JSON.stringify(body) }),
  graph: (agent_slug?: string) =>
    jreq<any>(`/v1/graph${agent_slug ? `?agent_id=${agent_slug}` : ""}`, {}, false),
  rebuildGraph: () => jreq<any>("/v1/graph/rebuild", { method: "POST" }, false),

  // billing (JWT)
  plans: () => jreq<any[]>("/v1/billing/plans"),
  billingStatus: () => jreq<any>("/v1/billing/status"),
  subscribe: (plan: string) =>
    jreq<any>("/v1/billing/subscribe", { method: "POST", body: JSON.stringify({ plan }) }),

  // public (no auth) — landing "Contact us"
  contact: (body: { name: string; email: string; message: string }) =>
    jreq<any>("/v1/contact", { method: "POST", body: JSON.stringify(body) }, false),
  publicPlans: () => jreq<any[]>("/v1/billing/plans/public", {}, false),

  // admin / operator (JWT, admin-email gated)
  adminContact: () => jreq<any[]>("/v1/admin/contact"),
  adminUsers: () => jreq<any[]>("/v1/admin/users"),
  adminSetUser: (id: string, disabled: boolean) =>
    jreq<any>(`/v1/admin/users/${id}`, { method: "POST", body: JSON.stringify({ disabled }) }),
};
