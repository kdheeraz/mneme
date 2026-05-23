"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, auth } from "@/lib/api";

type Mode = "login" | "signup";

export default function AuthPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("demo@mneme.dev");
  const [password, setPassword] = useState("demo1234");
  const [name, setName] = useState("");
  const [tenantName, setTenantName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (auth.token()) router.replace("/dashboard");
  }, [router]);

  const submit = async () => {
    setErr(null);
    setBusy(true);
    try {
      const result =
        mode === "login"
          ? await api.login({ email, password })
          : await api.signup({
              email,
              password,
              name: name || undefined,
              tenant_name: tenantName || undefined,
            });
      auth.setSession(result);
      router.push("/dashboard");
    } catch (e: any) {
      setErr(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <div className="panel w-full max-w-md p-8">
        <div className="flex items-baseline justify-between mb-1">
          <Link href="/" className="text-2xl font-bold text-ink hover:opacity-80">Mneme</Link>
          <span className="text-xs text-gray-500 mono">v0.2.0</span>
        </div>
        <p className="text-sm text-gray-600 mb-6">Memory-as-a-Service for LLM agents.</p>

        <div className="flex gap-1 border-b border-gray-200 mb-4">
          {(["login", "signup"] as Mode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition ${
                mode === m
                  ? "border-ink text-ink"
                  : "border-transparent text-gray-500 hover:text-gray-800"
              }`}
            >
              {m === "login" ? "Log in" : "Sign up"}
            </button>
          ))}
        </div>

        <div className="space-y-3">
          <Field label="Email">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
              autoFocus
            />
          </Field>
          <Field label="Password">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
            />
          </Field>
          {mode === "signup" && (
            <>
              <Field label="Name (optional)">
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                />
              </Field>
              <Field label="Workspace name (optional)">
                <input
                  value={tenantName}
                  onChange={(e) => setTenantName(e.target.value)}
                  placeholder="Acme Inc."
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                />
              </Field>
            </>
          )}
        </div>

        {err && <p className="text-red-600 text-xs mt-3">{err}</p>}

        <button
          onClick={submit}
          disabled={busy}
          className="mt-5 w-full bg-ink text-white rounded py-2 text-sm font-semibold hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "…" : mode === "login" ? "Log in" : "Create account"}
        </button>

        {mode === "login" && (
          <p className="text-[11px] text-gray-500 mt-4 text-center">
            Demo: <span className="mono">demo@mneme.dev / demo1234</span>
          </p>
        )}
      </div>
    </main>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-[11px] uppercase tracking-wider text-gray-500 mb-1">{label}</label>
      {children}
    </div>
  );
}
