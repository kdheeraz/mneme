"use client";
import { useEffect, useState, useCallback } from "react";
import useSWR from "swr";
import { api, auth } from "@/lib/api";

type Tab = "overview" | "agents" | "memories" | "search" | "ingest" | "traces";

export default function Dashboard() {
  const [tab, setTab] = useState<Tab>("overview");

  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "agents", label: "Agents" },
    { id: "memories", label: "Memories" },
    { id: "search", label: "Live Search" },
    { id: "ingest", label: "Ingest" },
    { id: "traces", label: "Traces" },
  ];

  return (
    <div>
      <div className="flex gap-1 border-b border-gray-200 mb-6">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition ${
              tab === t.id ? "border-ink text-ink" : "border-transparent text-gray-500 hover:text-gray-800"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "overview" && <Overview />}
      {tab === "agents" && <Agents />}
      {tab === "memories" && <Memories />}
      {tab === "search" && <Search />}
      {tab === "ingest" && <Ingest />}
      {tab === "traces" && <Traces />}
    </div>
  );
}

// ===================== Overview =====================

function Overview() {
  const { data: stats } = useSWR("stats", () => api.stats(), { refreshInterval: 5000 });
  if (!stats) return <div className="text-sm text-gray-500">Loading stats…</div>;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard label="Agents" value={stats.total_agents} />
        <StatCard label="Total memories" value={stats.total_memories} />
        <StatCard label="Ops last 24h" value={stats.recent_ops_24h} />
        <StatCard
          label="By kind"
          value={Object.keys(stats.memories_by_kind).length}
          sub={Object.entries(stats.memories_by_kind).map(([k, v]) => `${k}:${v}`).join("  ")}
        />
      </div>
      <div className="panel p-5">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-ink mb-3">Memories by agent</h3>
        {stats.memories_by_agent.length === 0 ? (
          <p className="text-sm text-gray-500">No memories yet — register an agent and call the API.</p>
        ) : (
          <div className="space-y-2">
            {stats.memories_by_agent.map((row: any) => {
              const max = Math.max(...stats.memories_by_agent.map((r: any) => r.count));
              const pct = (row.count / max) * 100;
              return (
                <div key={row.agent_id} className="flex items-center gap-3">
                  <div className="w-40 text-xs mono text-gray-700">{row.agent_id}</div>
                  <div className="flex-1 bg-gray-100 rounded h-5 overflow-hidden">
                    <div
                      style={{ width: `${pct}%` }}
                      className="h-full bg-accent flex items-center justify-end pr-2 text-[10px] text-white font-semibold"
                    >
                      {row.count}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <Consolidation />
    </div>
  );
}

function Consolidation() {
  const [threshold, setThreshold] = useState(0.92);
  const [useLlmMerge, setUseLlmMerge] = useState(false);
  const [decayHL, setDecayHL] = useState<string>("");
  const [dryRun, setDryRun] = useState(true);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setErr(null);
    setRes(null);
    try {
      const r = await api.consolidate({
        similarity_threshold: threshold,
        use_llm_merge: useLlmMerge,
        decay_half_life_days: decayHL ? parseFloat(decayHL) : undefined,
        dry_run: dryRun,
      });
      setRes(r);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel p-5">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-ink mb-1">
        Consolidation
      </h3>
      <p className="text-xs text-gray-500 mb-4">
        Finds near-duplicate memories within the same (agent, user) scope and merges them.
        Optionally uses each agent's LLM to merge content. Decay applies a half-life to importance.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="block text-[11px] uppercase tracking-wider text-gray-500 mb-1">
            similarity threshold: {threshold.toFixed(2)}
          </label>
          <input
            type="range"
            min={0.7}
            max={0.99}
            step={0.01}
            value={threshold}
            onChange={(e) => setThreshold(parseFloat(e.target.value))}
            className="w-full"
          />
        </div>
        <div>
          <label className="block text-[11px] uppercase tracking-wider text-gray-500 mb-1">
            decay half-life (days, optional)
          </label>
          <input
            value={decayHL}
            onChange={(e) => setDecayHL(e.target.value)}
            className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm mono"
            placeholder="e.g. 30"
          />
        </div>
        <div className="flex flex-col gap-2 text-xs text-gray-700 pt-5">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={useLlmMerge} onChange={(e) => setUseLlmMerge(e.target.checked)} />
            Use agent's LLM to merge content
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
            Dry-run (preview without persisting)
          </label>
        </div>
      </div>

      <button
        onClick={run}
        disabled={busy}
        className="mt-4 bg-ink text-white px-4 py-2 rounded text-sm font-semibold disabled:opacity-50"
      >
        {busy ? "Running…" : dryRun ? "Preview consolidation" : "Run consolidation"}
      </button>
      {err && <p className="text-red-600 text-xs mt-2">{err}</p>}

      {res && (
        <div className="mt-5 space-y-3">
          <div className="text-xs mono text-gray-600">
            {res.pairs_found} pairs · {res.merges_performed} merges
            {res.decayed_count > 0 && ` · ${res.decayed_count} decayed`}
            {" "}· {res.latency_ms}ms
          </div>
          {res.pairs.length === 0 ? (
            <p className="text-sm text-gray-500">
              No near-duplicate pairs found. Try lowering the threshold.
            </p>
          ) : (
            <div className="space-y-2">
              {res.pairs.map((p: any) => (
                <div key={p.kept_id + p.superseded_id} className="border border-gray-200 rounded p-3">
                  <div className="text-[11px] mono text-gray-500 mb-1">
                    sim {p.similarity.toFixed(3)}
                  </div>
                  <div className="text-sm">
                    <span className="tag" style={{ background: "#dcfce7", color: "#14532d" }}>
                      kept
                    </span>{" "}
                    {p.merged_content || p.kept_content}
                  </div>
                  <div className="text-sm text-gray-400 line-through mt-1">
                    <span
                      className="tag mr-1"
                      style={{ background: "#fee2e2", color: "#7f1d1d", textDecoration: "none" }}
                    >
                      superseded
                    </span>
                    {p.superseded_content}
                  </div>
                  {p.merged_content && (
                    <div className="text-[11px] text-purple-700 mt-1">
                      ↪ LLM-merged content replaced the kept one
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="panel p-4">
      <div className="text-[11px] uppercase tracking-wider text-gray-500">{label}</div>
      <div className="text-2xl font-bold text-ink mt-1">{value}</div>
      {sub && <div className="text-[11px] text-gray-500 mt-1 mono">{sub}</div>}
    </div>
  );
}

// ===================== Agents =====================

function Agents() {
  const { data: agents, mutate } = useSWR("agents", () => api.listAgents(), { refreshInterval: 5000 });
  const [openSlug, setOpenSlug] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <p className="text-sm text-gray-600">{agents?.length ?? 0} agents registered</p>
        <button
          onClick={() => setCreating(true)}
          className="bg-ink text-white text-sm font-semibold rounded px-4 py-2 hover:opacity-90"
        >
          + New agent
        </button>
      </div>

      {creating && (
        <CreateAgentForm
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            mutate();
          }}
        />
      )}

      <div className="panel divide-y divide-gray-100">
        {(agents ?? []).map((a: any) => (
          <AgentRow
            key={a.id}
            agent={a}
            open={openSlug === a.slug}
            onToggle={() => setOpenSlug(openSlug === a.slug ? null : a.slug)}
            onChanged={() => mutate()}
          />
        ))}
        {agents && agents.length === 0 && (
          <div className="p-6 text-sm text-gray-500">
            No agents yet. Click <b>+ New agent</b> to register one.
          </div>
        )}
      </div>
    </div>
  );
}

function AgentRow({
  agent,
  open,
  onToggle,
  onChanged,
}: {
  agent: any;
  open: boolean;
  onToggle: () => void;
  onChanged: () => void;
}) {
  const activate = () => {
    // pull / create an agent-scoped API key and set it as the active key for the SDK-like tabs
    (async () => {
      const keys = await api.listKeys(agent.slug);
      let k = keys[0]?.key;
      if (!k) {
        const created = await api.createKey({ label: "ui", agent_slug: agent.slug });
        k = created.key;
      }
      auth.setApiKey(k);
      alert(`Active agent: ${agent.slug}\nKey set for Memories / Search / Traces tabs.`);
    })();
  };

  return (
    <div>
      <div className="px-4 py-3 flex items-center gap-4">
        <div className="flex-1 cursor-pointer" onClick={onToggle}>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-ink">{agent.name}</span>
            <span className="tag mono">{agent.slug}</span>
            <span className="tag" style={{ background: "#fef3c7", color: "#92400e" }}>
              {agent.llm_provider}:{agent.llm_model}
            </span>
            <span className="tag" style={{ background: "#dcfce7", color: "#14532d" }}>
              emb: {agent.embedding_provider}
            </span>
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {agent.description || <i>no description</i>}  ·  {agent.memory_count} memories
          </div>
        </div>
        <button
          onClick={activate}
          className="text-xs bg-ink text-white px-3 py-1.5 rounded hover:opacity-90"
        >
          Use this agent
        </button>
      </div>
      {open && <AgentDetail agent={agent} onChanged={onChanged} />}
    </div>
  );
}

function AgentDetail({ agent, onChanged }: { agent: any; onChanged: () => void }) {
  const { data: keys, mutate: mutateKeys } = useSWR(`keys-${agent.slug}`, () => api.listKeys(agent.slug));
  const [edit, setEdit] = useState({
    name: agent.name,
    description: agent.description || "",
    llm_provider: agent.llm_provider,
    llm_model: agent.llm_model,
    llm_api_key: "",
    llm_base_url: agent.llm_base_url || "",
    embedding_provider: agent.embedding_provider,
    embedding_model: agent.embedding_model,
    embedding_api_key: "",
    embedding_base_url: agent.embedding_base_url || "",
    rerank_provider: agent.rerank_provider || "none",
    rerank_model: agent.rerank_model || "rerank-english-v3.0",
    rerank_api_key: "",
    auto_extract: agent.auto_extract,
  });
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);

  const onLlmProvider = (v: string) => {
    const base = v === "ollama" && !edit.llm_base_url ? "http://host.docker.internal:11434" : edit.llm_base_url;
    const model = v === "ollama" ? "llama3.2" : edit.llm_model;
    setEdit({ ...edit, llm_provider: v as any, llm_base_url: base, llm_model: model });
  };
  const onEmbProvider = (v: string) => {
    const base = v === "ollama" && !edit.embedding_base_url ? "http://host.docker.internal:11434" : edit.embedding_base_url;
    const model = v === "ollama" ? "nomic-embed-text" : edit.embedding_model;
    setEdit({ ...edit, embedding_provider: v as any, embedding_base_url: base, embedding_model: model });
  };

  const save = async () => {
    const patch: any = { ...edit };
    if (!patch.llm_api_key) delete patch.llm_api_key;
    if (!patch.embedding_api_key) delete patch.embedding_api_key;
    if (!patch.rerank_api_key) delete patch.rerank_api_key;
    await api.updateAgent(agent.slug, patch);
    onChanged();
  };

  const onRerank = (v: string) => {
    let model = edit.rerank_model;
    if (v === "cohere") model = "rerank-english-v3.0";
    if (v === "voyage") model = "rerank-2";
    if (v === "jina") model = "jina-reranker-v2-base-multilingual";
    setEdit({ ...edit, rerank_provider: v, rerank_model: model });
  };

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await api.testAgent(agent.slug));
    } catch (e: any) {
      setTestResult({ embedding_ok: false, llm_ok: false, embedding_error: e.message });
    } finally {
      setTesting(false);
    }
  };

  const del = async () => {
    if (!confirm(`Delete agent ${agent.slug}? This does NOT delete its memories.`)) return;
    await api.deleteAgent(agent.slug);
    onChanged();
  };

  const newKey = async () => {
    await api.createKey({ label: `key-${Date.now()}`, agent_slug: agent.slug });
    mutateKeys();
  };

  const removeKey = async (id: string) => {
    if (!confirm("Revoke this key?")) return;
    await api.deleteKey(id);
    mutateKeys();
  };

  return (
    <div className="bg-gray-50 px-4 py-4 space-y-5">
      <Section title="Config">
        <div className="grid grid-cols-2 gap-3">
          <Inp label="Name" v={edit.name} on={(v) => setEdit({ ...edit, name: v })} />
          <Inp label="Description" v={edit.description} on={(v) => setEdit({ ...edit, description: v })} />

          <Sel
            label="LLM provider"
            v={edit.llm_provider}
            options={["none", "openai", "anthropic", "ollama"]}
            on={onLlmProvider}
          />
          <Inp label="LLM model" v={edit.llm_model} on={(v) => setEdit({ ...edit, llm_model: v })} mono />
          {edit.llm_provider === "ollama" && (
            <div className="col-span-2">
              <Inp
                label="LLM base URL"
                v={edit.llm_base_url}
                on={(v) => setEdit({ ...edit, llm_base_url: v })}
                placeholder="http://host.docker.internal:11434 (local) or https://ollama.your-host.com"
                mono
              />
            </div>
          )}
          {edit.llm_provider !== "none" && edit.llm_provider !== "ollama" && (
            <div className="col-span-2">
              <Inp
                label={`LLM API key  ${agent.llm_api_key_set ? "(set ✓)" : ""}`}
                v={edit.llm_api_key}
                on={(v) => setEdit({ ...edit, llm_api_key: v })}
                placeholder="sk-…  (leave blank to keep current)"
                mono
              />
            </div>
          )}

          <Sel
            label="Embedding provider"
            v={edit.embedding_provider}
            options={["fake", "openai", "ollama"]}
            on={onEmbProvider}
          />
          <Inp label="Embedding model" v={edit.embedding_model} on={(v) => setEdit({ ...edit, embedding_model: v })} mono />
          {edit.embedding_provider === "ollama" && (
            <div className="col-span-2">
              <Inp
                label="Embedding base URL"
                v={edit.embedding_base_url}
                on={(v) => setEdit({ ...edit, embedding_base_url: v })}
                placeholder="http://host.docker.internal:11434 (local) or remote Ollama URL"
                mono
              />
            </div>
          )}
          {edit.embedding_provider === "openai" && (
            <div className="col-span-2">
              <Inp
                label={`Embedding API key  ${agent.embedding_api_key_set ? "(set ✓)" : ""}`}
                v={edit.embedding_api_key}
                on={(v) => setEdit({ ...edit, embedding_api_key: v })}
                placeholder="sk-…  (leave blank to keep current)"
                mono
              />
            </div>
          )}

          <Sel
            label="Reranker"
            v={edit.rerank_provider}
            options={["none", "cohere", "voyage", "jina"]}
            on={onRerank}
          />
          <Inp label="Rerank model" v={edit.rerank_model} on={(v) => setEdit({ ...edit, rerank_model: v })} mono />
          {edit.rerank_provider !== "none" && (
            <div className="col-span-2">
              <Inp
                label={`Rerank API key  ${agent.rerank_api_key_set ? "(set ✓)" : ""}`}
                v={edit.rerank_api_key}
                on={(v) => setEdit({ ...edit, rerank_api_key: v })}
                placeholder="(leave blank to keep current)"
                mono
              />
            </div>
          )}

          <label className="flex items-center gap-2 text-xs text-gray-600 col-span-2">
            <input
              type="checkbox"
              checked={edit.auto_extract}
              onChange={(e) => setEdit({ ...edit, auto_extract: e.target.checked })}
            />
            Auto-extract memories from raw input (uses agent's LLM)
          </label>
        </div>

        <div className="flex gap-2 mt-3 items-center">
          <button onClick={save} className="bg-ink text-white px-3 py-1.5 rounded text-xs font-semibold">
            Save changes
          </button>
          <button
            onClick={runTest}
            disabled={testing}
            className="border border-ink text-ink px-3 py-1.5 rounded text-xs font-semibold hover:bg-white disabled:opacity-50"
          >
            {testing ? "Testing…" : "Test connection"}
          </button>
          <button onClick={del} className="text-xs text-red-600 hover:text-red-800 ml-auto">
            Delete agent
          </button>
        </div>

        {testResult && (
          <div className="mt-3 panel p-3 text-xs space-y-1">
            <div>
              <span className={testResult.embedding_ok ? "text-green-700" : "text-red-700"}>
                {testResult.embedding_ok ? "✓" : "✗"} Embedding
              </span>{" "}
              {testResult.embedding_dim && <span className="text-gray-500">(dim {testResult.embedding_dim})</span>}
              {testResult.embedding_error && (
                <span className="mono text-red-600 break-all">  {testResult.embedding_error}</span>
              )}
            </div>
            <div>
              <span className={testResult.llm_ok ? "text-green-700" : "text-red-700"}>
                {testResult.llm_ok ? "✓" : "✗"} LLM
              </span>{" "}
              {testResult.llm_sample && <span className="text-gray-700">— {testResult.llm_sample}</span>}
              {testResult.llm_error && (
                <span className="mono text-red-600 break-all">  {testResult.llm_error}</span>
              )}
            </div>
          </div>
        )}
      </Section>

      <Section title="API keys">
        <div className="space-y-2">
          {(keys ?? []).map((k: any) => (
            <div key={k.id} className="flex items-center gap-3 text-xs">
              <span className="mono break-all flex-1">{k.key}</span>
              <span className="text-gray-500">{k.label}</span>
              <button onClick={() => removeKey(k.id)} className="text-red-500 hover:text-red-700">
                revoke
              </button>
            </div>
          ))}
          {keys && keys.length === 0 && (
            <p className="text-xs text-gray-500">No keys yet.</p>
          )}
          <button
            onClick={newKey}
            className="text-xs border border-ink text-ink px-3 py-1.5 rounded font-semibold hover:bg-white"
          >
            + Generate key
          </button>
        </div>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-[11px] uppercase tracking-wider text-gray-600 font-semibold mb-2">{title}</h4>
      {children}
    </div>
  );
}

function Inp({
  label, v, on, placeholder, mono,
}: { label: string; v: string; on: (v: string) => void; placeholder?: string; mono?: boolean }) {
  return (
    <div>
      <label className="block text-[11px] uppercase tracking-wider text-gray-500 mb-1">{label}</label>
      <input
        value={v}
        onChange={(e) => on(e.target.value)}
        placeholder={placeholder}
        className={`w-full border border-gray-300 rounded px-2 py-1.5 text-sm ${mono ? "mono" : ""}`}
      />
    </div>
  );
}

function Sel({
  label, v, on, options,
}: { label: string; v: string; on: (v: string) => void; options: string[] }) {
  return (
    <div>
      <label className="block text-[11px] uppercase tracking-wider text-gray-500 mb-1">{label}</label>
      <select
        value={v}
        onChange={(e) => on(e.target.value)}
        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm bg-white"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </div>
  );
}

function CreateAgentForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [v, setV] = useState({
    name: "",
    slug: "",
    description: "",
    llm_provider: "none" as "none" | "openai" | "anthropic" | "ollama",
    llm_model: "gpt-4o-mini",
    llm_api_key: "",
    llm_base_url: "",
    embedding_provider: "fake" as "fake" | "openai" | "ollama",
    embedding_model: "text-embedding-3-small",
    embedding_api_key: "",
    embedding_base_url: "",
    rerank_provider: "none" as "none" | "cohere" | "voyage" | "jina",
    rerank_model: "rerank-english-v3.0",
    rerank_api_key: "",
    auto_extract: false,
  });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onRerank = (x: string) => {
    let model = v.rerank_model;
    if (x === "cohere") model = "rerank-english-v3.0";
    if (x === "voyage") model = "rerank-2";
    if (x === "jina") model = "jina-reranker-v2-base-multilingual";
    setV({ ...v, rerank_provider: x as any, rerank_model: model });
  };

  const onLlm = (x: string) => {
    const base = x === "ollama" && !v.llm_base_url ? "http://host.docker.internal:11434" : v.llm_base_url;
    const model =
      x === "ollama" ? "llama3.2" :
      x === "anthropic" ? "claude-3-5-sonnet-latest" :
      "gpt-4o-mini";
    setV({ ...v, llm_provider: x as any, llm_base_url: base, llm_model: model });
  };
  const onEmb = (x: string) => {
    const base = x === "ollama" && !v.embedding_base_url ? "http://host.docker.internal:11434" : v.embedding_base_url;
    const model = x === "ollama" ? "nomic-embed-text" : "text-embedding-3-small";
    setV({ ...v, embedding_provider: x as any, embedding_base_url: base, embedding_model: model });
  };

  const create = async () => {
    setErr(null);
    setBusy(true);
    try {
      const payload: any = { ...v };
      if (!payload.slug) delete payload.slug;
      if (!payload.llm_api_key) delete payload.llm_api_key;
      if (!payload.embedding_api_key) delete payload.embedding_api_key;
      if (!payload.llm_base_url) delete payload.llm_base_url;
      if (!payload.embedding_base_url) delete payload.embedding_base_url;
      if (!payload.rerank_api_key) delete payload.rerank_api_key;
      await api.createAgent(payload);
      onCreated();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-ink">Register new agent</h3>
        <button onClick={onClose} className="text-xs text-gray-500 hover:text-gray-800">cancel</button>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Inp label="Name *" v={v.name} on={(x) => setV({ ...v, name: x })} placeholder="Research Bot" />
        <Inp label="Slug (auto if blank)" v={v.slug} on={(x) => setV({ ...v, slug: x })} placeholder="research-bot" mono />
        <div className="col-span-2">
          <Inp label="Description" v={v.description} on={(x) => setV({ ...v, description: x })} />
        </div>

        <Sel label="LLM provider" v={v.llm_provider} options={["none", "openai", "anthropic", "ollama"]} on={onLlm} />
        <Inp label="LLM model" v={v.llm_model} on={(x) => setV({ ...v, llm_model: x })} mono />
        {v.llm_provider === "ollama" && (
          <div className="col-span-2">
            <Inp
              label="LLM base URL"
              v={v.llm_base_url}
              on={(x) => setV({ ...v, llm_base_url: x })}
              mono
              placeholder="http://host.docker.internal:11434 (local Ollama) or remote URL"
            />
          </div>
        )}
        {(v.llm_provider === "openai" || v.llm_provider === "anthropic") && (
          <div className="col-span-2">
            <Inp label="LLM API key (optional)" v={v.llm_api_key} on={(x) => setV({ ...v, llm_api_key: x })} mono placeholder="sk-..." />
          </div>
        )}

        <Sel label="Embedding provider" v={v.embedding_provider} options={["fake", "openai", "ollama"]} on={onEmb} />
        <Inp label="Embedding model" v={v.embedding_model} on={(x) => setV({ ...v, embedding_model: x })} mono />
        {v.embedding_provider === "ollama" && (
          <div className="col-span-2">
            <Inp
              label="Embedding base URL"
              v={v.embedding_base_url}
              on={(x) => setV({ ...v, embedding_base_url: x })}
              mono
              placeholder="http://host.docker.internal:11434 (local) or remote Ollama URL"
            />
          </div>
        )}
        {v.embedding_provider === "openai" && (
          <div className="col-span-2">
            <Inp label="Embedding API key (optional)" v={v.embedding_api_key} on={(x) => setV({ ...v, embedding_api_key: x })} mono placeholder="sk-..." />
          </div>
        )}

        <Sel label="Reranker" v={v.rerank_provider} options={["none", "cohere", "voyage", "jina"]} on={onRerank} />
        <Inp label="Rerank model" v={v.rerank_model} on={(x) => setV({ ...v, rerank_model: x })} mono />
        {v.rerank_provider !== "none" && (
          <div className="col-span-2">
            <Inp label="Rerank API key (optional)" v={v.rerank_api_key} on={(x) => setV({ ...v, rerank_api_key: x })} mono placeholder="leave blank to set later" />
          </div>
        )}

        <label className="flex items-center gap-2 text-xs text-gray-600 col-span-2">
          <input
            type="checkbox"
            checked={v.auto_extract}
            onChange={(e) => setV({ ...v, auto_extract: e.target.checked })}
          />
          Auto-extract memories from raw input (uses agent's LLM)
        </label>
      </div>
      {err && <p className="text-red-600 text-xs mt-3">{err}</p>}
      <button
        onClick={create}
        disabled={busy || !v.name}
        className="mt-4 bg-ink text-white px-4 py-2 rounded text-sm font-semibold disabled:opacity-50"
      >
        {busy ? "…" : "Create + generate API key"}
      </button>
      {v.embedding_provider === "ollama" && (
        <p className="text-[11px] text-amber-700 mt-2">
          ⚠ Ollama embedding dims vary by model — <span className="mono">nomic-embed-text</span>=768,{" "}
          <span className="mono">mxbai-embed-large</span>=1024. Mneme's tenant dim is 1536 by default;
          set <span className="mono">MNEME_EMBEDDING_DIM</span> in <span className="mono">.env</span> and{" "}
          <span className="mono">make reset</span> if you want to use these.
        </p>
      )}
    </div>
  );
}

// ===================== Memories / Search / Traces =====================
// (These use the active API key from localStorage — set via "Use this agent"
//  on the Agents tab, or use a tenant-wide key set manually.)

function ActiveKeyBanner() {
  const k = typeof window !== "undefined" ? auth.apiKey() : "";
  if (!k) {
    return (
      <div className="panel p-3 text-xs text-gray-700 mb-4">
        No active API key. Go to the <b>Agents</b> tab and click <b>Use this agent</b> to select one.
        These tabs call the API as if you were that agent's SDK client.
      </div>
    );
  }
  return (
    <div className="panel p-3 text-xs text-gray-600 mb-4 flex items-center gap-2">
      <span className="tag">active key</span>
      <span className="mono break-all">{k.slice(0, 24)}…</span>
    </div>
  );
}

function Memories() {
  const [agent, setAgent] = useState("");
  const [user, setUser] = useState("");
  const [kind, setKind] = useState("");

  const { data, mutate } = useSWR(
    ["memories", agent, user, kind],
    () => api.listMemories({ agent_id: agent || undefined, user_id: user || undefined, kind: kind || undefined, limit: "100" }),
    { refreshInterval: 4000 }
  );

  const del = async (id: string) => {
    if (!confirm("Delete this memory?")) return;
    await api.deleteMemory(id);
    mutate();
  };

  return (
    <div className="space-y-4">
      <ActiveKeyBanner />
      <div className="flex flex-wrap gap-2 items-end">
        <FilterInput label="agent_id" value={agent} onChange={setAgent} />
        <FilterInput label="user_id" value={user} onChange={setUser} />
        <div>
          <label className="block text-[11px] uppercase tracking-wider text-gray-500 mb-1">kind</label>
          <select className="border border-gray-300 rounded px-2 py-1.5 text-sm" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">all</option>
            <option value="semantic">semantic</option>
            <option value="episodic">episodic</option>
            <option value="procedural">procedural</option>
          </select>
        </div>
        <div className="ml-auto text-xs text-gray-500">{data?.length ?? 0} memories</div>
      </div>

      <div className="panel divide-y divide-gray-100">
        {(data ?? []).map((m: any) => (
          <div key={m.id} className="p-4 flex gap-4">
            <div className="flex-1">
              <div className="text-sm">{m.content}</div>
              <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px] text-gray-500 mono">
                <span className="tag">{m.kind}</span>
                {m.agent_id && <span>agent:{m.agent_id}</span>}
                {m.user_id && <span>user:{m.user_id}</span>}
                {m.session_id && <span>sess:{m.session_id}</span>}
                <span>imp:{m.importance}</span>
                <span>hits:{m.access_count}</span>
                <span>·  {new Date(m.created_at).toLocaleString()}</span>
              </div>
            </div>
            <button onClick={() => del(m.id)} className="text-xs text-red-500 hover:text-red-700">delete</button>
          </div>
        ))}
        {data && data.length === 0 && <div className="p-6 text-sm text-gray-500">No memories match those filters.</div>}
      </div>
    </div>
  );
}

function FilterInput({
  label, value, onChange,
}: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="block text-[11px] uppercase tracking-wider text-gray-500 mb-1">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="border border-gray-300 rounded px-2 py-1.5 text-sm mono w-44"
        placeholder="filter…"
      />
    </div>
  );
}

function Search() {
  const [q, setQ] = useState("what does the user care about?");
  const [agent, setAgent] = useState("");
  const [user, setUser] = useState("");
  const [crossAgent, setCrossAgent] = useState(false);
  const [recency, setRecency] = useState(0.15);
  const [mode, setMode] = useState<"hybrid" | "vector" | "lexical">("hybrid");
  const [rerank, setRerank] = useState(false);
  const [rewrite, setRewrite] = useState(false);
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.searchMemories({
        query: q,
        agent_id: agent || undefined,
        user_id: user || undefined,
        cross_agent: crossAgent,
        recency_weight: recency,
        mode,
        rerank,
        rewrite,
        limit: 10,
      });
      setRes(r);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }, [q, agent, user, crossAgent, recency, mode, rerank, rewrite]);

  return (
    <div className="space-y-4">
      <ActiveKeyBanner />
      <div className="grid md:grid-cols-2 gap-6">
        <div className="panel p-5 space-y-4">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-ink">Query</h3>
          <textarea value={q} onChange={(e) => setQ(e.target.value)} className="w-full border border-gray-300 rounded px-3 py-2 text-sm h-24" />
          <div className="grid grid-cols-2 gap-2">
            <FilterInput label="agent_id" value={agent} onChange={setAgent} />
            <FilterInput label="user_id" value={user} onChange={setUser} />
          </div>
          <label className="flex items-center gap-2 text-xs text-gray-600">
            <input type="checkbox" checked={crossAgent} onChange={(e) => setCrossAgent(e.target.checked)} />
            Cross-agent search
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-600">
            <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} />
            Cross-encoder rerank  <span className="text-gray-400">(requires reranker on agent)</span>
          </label>
          <label className="flex items-center gap-2 text-xs text-gray-600">
            <input type="checkbox" checked={rewrite} onChange={(e) => setRewrite(e.target.checked)} />
            Query rewrite (LLM expansion)  <span className="text-gray-400">(requires LLM on agent)</span>
          </label>

          <div>
            <label className="block text-[11px] uppercase tracking-wider text-gray-500 mb-1">retrieval mode</label>
            <div className="flex gap-1 text-xs">
              {(["hybrid", "vector", "lexical"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={`flex-1 px-2 py-1.5 rounded font-semibold border ${
                    mode === m ? "bg-ink text-white border-ink" : "bg-white text-gray-700 border-gray-300 hover:border-gray-500"
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-gray-500 mt-1">
              {mode === "hybrid" && "Vector + BM25-style lexical, fused via RRF (k=60)."}
              {mode === "vector" && "Embedding cosine similarity only."}
              {mode === "lexical" && "Postgres tsvector + ts_rank_cd only."}
            </p>
          </div>

          <div>
            <label className="block text-[11px] uppercase tracking-wider text-gray-500 mb-1">
              recency weight: {recency.toFixed(2)}
            </label>
            <input type="range" min={0} max={1} step={0.05} value={recency} onChange={(e) => setRecency(parseFloat(e.target.value))} className="w-full" />
          </div>
          <button onClick={run} disabled={busy} className="w-full bg-ink text-white rounded py-2 text-sm font-semibold disabled:opacity-50">
            {busy ? "Searching…" : "Search"}
          </button>
          {err && <p className="text-red-600 text-xs">{err}</p>}
        </div>
        <div className="panel p-5">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-ink mb-3">Results</h3>
          {!res && <p className="text-sm text-gray-500">Run a search to see retrieval traces.</p>}
          {res && (
            <>
              <div className="text-xs text-gray-500 mb-3 mono">
                latency: {res.latency_ms}ms  ·  trace: {res.trace_id.slice(0, 8)}…
              </div>
              {res.rewritten_query && (
                <div className="text-xs mb-3 panel p-2 bg-purple-50 border-purple-200">
                  <div className="text-[10px] uppercase tracking-wider text-purple-700 font-semibold mb-0.5">
                    expanded query
                  </div>
                  <div className="text-gray-700">{res.rewritten_query}</div>
                </div>
              )}
              {res.rewrite_error && (
                <div className="text-xs mb-3 panel p-2 bg-red-50 border-red-200 mono text-red-700">
                  rewrite error: {res.rewrite_error}
                </div>
              )}
              <div className="space-y-3">
                {res.hits.map((h: any, i: number) => (
                  <div key={h.memory.id} className="border-l-2 border-accent pl-3">
                    <div className="text-[11px] mono text-gray-500 mb-0.5">
                      #{i + 1}  ·  final {h.final_score.toFixed(4)}
                      {h.rerank_score != null
                        ? `  ·  rerank ${h.rerank_score.toFixed(4)}`
                        : `  ·  rrf ${h.rrf_score.toFixed(4)}`}
                      {" "}·  recency {h.recency_boost.toFixed(3)}
                    </div>
                    <div className="text-[11px] mono text-gray-500 mb-1 flex flex-wrap gap-2">
                      {h.vector_rank != null && (
                        <span className="tag" style={{ background: "#dbeafe", color: "#1e3a8a" }}>
                          vec #{h.vector_rank} · sim {h.similarity.toFixed(3)}
                        </span>
                      )}
                      {h.lexical_rank != null && (
                        <span className="tag" style={{ background: "#fef3c7", color: "#854d0e" }}>
                          lex #{h.lexical_rank} · score {h.lexical_score.toFixed(3)}
                        </span>
                      )}
                      {h.rerank_score != null && (
                        <span className="tag" style={{ background: "#ede9fe", color: "#5b21b6" }}>
                          rerank {h.rerank_score.toFixed(3)}
                        </span>
                      )}
                    </div>
                    <div className="text-sm">{h.memory.content}</div>
                    <div className="text-[11px] mono text-gray-500 mt-0.5">
                      {h.memory.agent_id && `agent:${h.memory.agent_id} `}
                      {h.memory.user_id && `user:${h.memory.user_id} `}
                      <span className="tag ml-1">{h.memory.kind}</span>
                    </div>
                  </div>
                ))}
                {res.hits.length === 0 && <p className="text-sm text-gray-500">No memories matched.</p>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Ingest() {
  const SAMPLE = `[USER] Hey, just wrapping up — I prefer Tailwind over plain CSS, and from now on please always include a "what changed" line at the top of PR descriptions. Also we just shipped the auth migration yesterday (March 14), and I'm meeting Priya from Accel on Tuesday at 3pm.`;
  const [text, setText] = useState(SAMPLE);
  const [user, setUser] = useState("user_42");
  const [session, setSession] = useState("");
  const [persist, setPersist] = useState(true);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setErr(null);
    setRes(null);
    try {
      const r = await api.ingest({
        text,
        user_id: user || undefined,
        session_id: session || undefined,
        persist,
      });
      setRes(r);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <ActiveKeyBanner />

      <div className="grid md:grid-cols-2 gap-6">
        <div className="panel p-5 space-y-3">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-ink">
            Conversation / text
          </h3>
          <p className="text-xs text-gray-500">
            Paste a conversation or raw text. The active agent's LLM will extract atomic memories,
            each classified as semantic / episodic / procedural, then write them to the store.
          </p>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm h-56 mono"
            placeholder="[USER] ...&#10;[ASSISTANT] ..."
          />
          <div className="grid grid-cols-2 gap-2">
            <FilterInput label="user_id" value={user} onChange={setUser} />
            <FilterInput label="session_id" value={session} onChange={setSession} />
          </div>
          <label className="flex items-center gap-2 text-xs text-gray-600">
            <input
              type="checkbox"
              checked={persist}
              onChange={(e) => setPersist(e.target.checked)}
            />
            Persist extracted memories (uncheck for dry-run)
          </label>
          <button
            onClick={run}
            disabled={busy || !text.trim()}
            className="w-full bg-ink text-white rounded py-2 text-sm font-semibold disabled:opacity-50"
          >
            {busy ? "Extracting…" : "Run extraction"}
          </button>
          {err && <p className="text-red-600 text-xs">{err}</p>}
        </div>

        <div className="panel p-5">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-ink mb-3">
            Extracted memories
          </h3>
          {!res && (
            <p className="text-sm text-gray-500">
              Run extraction. Make sure the active agent has an LLM configured (Ollama works great).
            </p>
          )}
          {res && (
            <>
              <div className="text-xs text-gray-500 mb-3 mono">
                {res.extracted} extracted · {res.persisted} persisted · {res.latency_ms}ms
              </div>
              <div className="space-y-2">
                {(res.memories || []).map((m: any) => (
                  <div key={m.id} className="border-l-2 border-accent pl-3 py-1">
                    <div className="text-sm">{m.content}</div>
                    <div className="text-[11px] mono text-gray-500 mt-0.5">
                      <span className="tag">{m.kind}</span>{" "}
                      {m.user_id && `user:${m.user_id}`}
                    </div>
                  </div>
                ))}
                {res.memories && res.memories.length === 0 && (
                  <p className="text-xs text-gray-500">
                    Nothing extracted. The LLM may have decided there was nothing worth remembering, or the response wasn't parseable JSON — check the raw response below.
                  </p>
                )}
              </div>
              {res.raw_llm_response && (
                <details className="mt-4">
                  <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-800">
                    raw LLM response
                  </summary>
                  <pre className="mt-2 text-xs mono whitespace-pre-wrap bg-gray-50 p-2 rounded border border-gray-200 max-h-60 overflow-auto">
                    {res.raw_llm_response}
                  </pre>
                </details>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Traces() {
  const { data } = useSWR("traces", () => api.listTraces({ limit: "200" }), { refreshInterval: 3000 });
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="panel divide-y divide-gray-100">
      <div className="px-4 py-2 grid grid-cols-12 text-[11px] uppercase tracking-wider text-gray-500">
        <div className="col-span-2">When</div>
        <div className="col-span-1">Op</div>
        <div className="col-span-2">Agent</div>
        <div className="col-span-5">Query / preview</div>
        <div className="col-span-1">Hits</div>
        <div className="col-span-1">Latency</div>
      </div>
      {(data ?? []).map((t: any) => {
        const hitsArr = Array.isArray(t.results) ? t.results : t.results?.hits;
        const hitCount = Array.isArray(hitsArr) ? hitsArr.length : 0;
        const isOpen = open === t.id;
        return (
          <div key={t.id}>
            <div onClick={() => setOpen(isOpen ? null : t.id)} className="px-4 py-3 grid grid-cols-12 items-center cursor-pointer hover:bg-gray-50 text-sm">
              <div className="col-span-2 text-xs mono text-gray-600">{new Date(t.created_at).toLocaleTimeString()}</div>
              <div className="col-span-1"><span className="tag">{t.op}</span></div>
              <div className="col-span-2 text-xs mono text-gray-700">{t.agent_id || "-"}</div>
              <div className="col-span-5 truncate text-xs">{t.query || "(no query)"}</div>
              <div className="col-span-1 text-xs mono">{hitCount}</div>
              <div className="col-span-1 text-xs mono">{t.latency_ms ?? "-"}ms</div>
            </div>
            {isOpen && (
              <div className="px-4 py-3 bg-gray-50 text-xs mono whitespace-pre-wrap">
                {JSON.stringify(t.results, null, 2)}
              </div>
            )}
          </div>
        );
      })}
      {data && data.length === 0 && <div className="p-6 text-sm text-gray-500">No traces yet. Try a search.</div>}
    </div>
  );
}
