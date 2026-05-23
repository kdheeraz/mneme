import Link from "next/link";
import ContactForm from "./contact-form";
import PricingSection from "./pricing-section";

// Single source of truth for the product name — change here to rebrand the landing.
const BRAND = "Mneme";

const FEATURES = [
  {
    title: "Hybrid retrieval",
    body: "Vector + lexical (BM25-style) search fused with Reciprocal Rank Fusion, optional cross-encoder rerank, and recency-aware ranking. Every hit is explainable.",
  },
  {
    title: "Self-maintaining memory",
    body: "Write-time reconciliation decides ADD / UPDATE / DELETE so facts stay current — no contradictions piling up. Consolidation dedupes and decays the rest.",
  },
  {
    title: "Auto-extraction",
    body: "Drop in a conversation; an LLM distills it into atomic, typed memories (semantic / episodic / procedural) and skips the chit-chat.",
  },
  {
    title: "Graph memory",
    body: "Extracts entities and relationships into a knowledge graph, then traverses it at query time to surface connected context.",
  },
  {
    title: "Any model",
    body: "OpenAI, Anthropic, AWS Bedrock, and Ollama — local or cloud. Per-agent config for LLM, embeddings, and reranker. Bring your own keys.",
  },
  {
    title: "Built for teams",
    body: "Multi-tenant workspaces, per-agent isolation, a shared memory pool, plan limits, usage metering, and full operation traces.",
  },
];

const CODE = `from mneme import Mneme

m = Mneme(api_key="...")

# remember
m.add("User is vegetarian and lives in Bangalore", user_id="u1")

# recall — across every future conversation
m.search("what does the user eat?", user_id="u1")
# -> "User is vegetarian"`;

export default function Landing() {
  return (
    <main className="min-h-screen text-ink">
      {/* Nav */}
      <header className="sticky top-0 z-20 backdrop-blur bg-[#f6f7fb]/80 border-b border-gray-200">
        <nav className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <span className="text-lg font-bold tracking-tight">{BRAND}</span>
          <div className="flex items-center gap-5 text-sm">
            <a href="#features" className="text-gray-600 hover:text-ink hidden sm:inline">Features</a>
            <a href="#code" className="text-gray-600 hover:text-ink hidden sm:inline">Developers</a>
            <a href="#pricing" className="text-gray-600 hover:text-ink hidden sm:inline">Pricing</a>
            <a href="#contact" className="text-gray-600 hover:text-ink hidden sm:inline">Contact</a>
            <Link href="/login" className="text-gray-600 hover:text-ink">Log in</Link>
            <Link href="/login" className="bg-ink text-white rounded-lg px-4 py-2 font-semibold hover:opacity-90">
              Get started
            </Link>
          </div>
        </nav>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-ink to-accent" />
        <div
          className="absolute inset-0 opacity-[0.06]"
          style={{ backgroundImage: "radial-gradient(circle at 1px 1px, white 1px, transparent 0)", backgroundSize: "28px 28px" }}
        />
        <div className="relative max-w-6xl mx-auto px-6 py-24 sm:py-32 text-center text-white">
          <span className="inline-block tag !bg-white/10 !text-white/90 mb-6">Memory-as-a-Service for AI agents</span>
          <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight leading-[1.05]">
            Long-term memory<br />
            <span className="text-white/70">for your AI agents.</span>
          </h1>
          <p className="mt-6 max-w-2xl mx-auto text-lg text-white/80">
            Drop-in memory that remembers across every conversation — hybrid search,
            auto-extraction, and self-maintaining recall. One API call to remember,
            one to recall.
          </p>
          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <Link href="/login" className="bg-white text-ink rounded-lg px-6 py-3 font-semibold hover:opacity-90">
              Get started free
            </Link>
            <Link href="/login" className="border border-white/30 text-white rounded-lg px-6 py-3 font-semibold hover:bg-white/10">
              Live demo →
            </Link>
          </div>
          <p className="mt-4 text-xs text-white/50">Self-hostable · open SDKs · runs on local or cloud models</p>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="max-w-6xl mx-auto px-6 py-20 sm:py-24">
        <div className="max-w-2xl">
          <h2 className="text-3xl font-bold tracking-tight">Not a vector DB. A memory engine.</h2>
          <p className="mt-3 text-gray-600">
            Storage is the easy part. {BRAND} handles retrieval quality, keeping facts
            current, and the messy middle so your agents actually feel like they remember.
          </p>
        </div>
        <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="panel p-6 hover:border-accent transition">
              <h3 className="font-semibold text-ink">{f.title}</h3>
              <p className="mt-2 text-sm text-gray-600 leading-relaxed">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Code / developers */}
      <section id="code" className="bg-white border-y border-gray-200">
        <div className="max-w-6xl mx-auto px-6 py-20 sm:py-24 grid lg:grid-cols-2 gap-12 items-center">
          <div>
            <span className="tag mb-4">Developers</span>
            <h2 className="text-3xl font-bold tracking-tight">Two calls. That's the integration.</h2>
            <p className="mt-3 text-gray-600 leading-relaxed">
              Zero-dependency Python and TypeScript SDKs, plus a clean REST API with
              OpenAPI docs. Add a memory after each turn, search before the next one —
              {" "}{BRAND} handles extraction, ranking, and dedup.
            </p>
            <ul className="mt-6 space-y-2 text-sm text-gray-700">
              {["Python + JS/TS SDKs", "REST API (OpenAPI)", "Per-agent keys, encrypted secrets", "Full traces for every operation"].map((x) => (
                <li key={x} className="flex items-center gap-2">
                  <span className="text-accent">✓</span> {x}
                </li>
              ))}
            </ul>
          </div>
          <div className="panel overflow-hidden">
            <div className="flex items-center gap-1.5 px-4 py-3 border-b border-gray-200 bg-gray-50">
              <span className="w-3 h-3 rounded-full bg-red-400" />
              <span className="w-3 h-3 rounded-full bg-yellow-400" />
              <span className="w-3 h-3 rounded-full bg-green-400" />
              <span className="ml-2 text-xs text-gray-500 mono">quickstart.py</span>
            </div>
            <pre className="mono text-[13px] leading-relaxed p-5 overflow-x-auto bg-ink text-gray-100">
{CODE}
            </pre>
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="max-w-6xl mx-auto px-6 py-20 sm:py-24">
        <div className="max-w-2xl mx-auto text-center mb-12">
          <span className="tag mb-4">Pricing</span>
          <h2 className="text-3xl font-bold tracking-tight">Start free. Scale when you need to.</h2>
          <p className="mt-3 text-gray-600">
            Usage-based tiers by agents and memories. Self-host for unlimited — it's open.
          </p>
        </div>
        <PricingSection />
      </section>

      {/* CTA */}
      <section className="max-w-6xl mx-auto px-6 py-20 sm:py-24 text-center">
        <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">Give your agents a memory.</h2>
        <p className="mt-3 text-gray-600">Spin up a workspace in seconds. Free to start, self-host anytime.</p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Link href="/login" className="bg-ink text-white rounded-lg px-6 py-3 font-semibold hover:opacity-90">
            Get started free
          </Link>
          <Link href="/login" className="border border-gray-300 rounded-lg px-6 py-3 font-semibold hover:bg-white">
            Try the live demo
          </Link>
        </div>
      </section>

      {/* Contact */}
      <section id="contact" className="bg-white border-t border-gray-200">
        <div className="max-w-3xl mx-auto px-6 py-20 sm:py-24">
          <div className="text-center mb-10">
            <span className="tag mb-4">Contact us</span>
            <h2 className="text-3xl font-bold tracking-tight">Talk to us</h2>
            <p className="mt-3 text-gray-600">
              Questions, a use case, or want a hand getting set up? Send a note and we'll reply.
            </p>
          </div>
          <ContactForm />
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-gray-200">
        <div className="max-w-6xl mx-auto px-6 py-10 flex flex-col sm:flex-row items-center justify-between gap-3 text-sm text-gray-500">
          <span className="font-semibold text-ink">{BRAND}</span>
          <span>Memory-as-a-Service for LLM agents</span>
          <Link href="/login" className="hover:text-ink">Dashboard →</Link>
        </div>
      </footer>
    </main>
  );
}
