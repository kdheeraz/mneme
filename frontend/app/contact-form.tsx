"use client";
import { useState } from "react";
import { api } from "@/lib/api";

export default function ContactForm() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await api.contact({ name, email, message });
      setDone(true);
      setName("");
      setEmail("");
      setMessage("");
    } catch (e: any) {
      setErr(e.message || "Something went wrong — please try again.");
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="panel p-8 text-center">
        <p className="text-lg font-semibold text-ink">Thanks — message received.</p>
        <p className="mt-1 text-sm text-gray-600">We'll get back to you at the email you provided.</p>
        <button onClick={() => setDone(false)} className="mt-4 text-sm text-accent hover:underline">
          Send another
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="panel p-6 space-y-4">
      <div className="grid sm:grid-cols-2 gap-4">
        <Field label="Name">
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Jane Doe"
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
          />
        </Field>
        <Field label="Email">
          <input
            required
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="jane@acme.com"
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
          />
        </Field>
      </div>
      <Field label="Query">
        <textarea
          required
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={4}
          placeholder="How can we help?"
          className="w-full border border-gray-300 rounded px-3 py-2 text-sm resize-y"
        />
      </Field>
      {err && <p className="text-red-600 text-xs">{err}</p>}
      <button
        type="submit"
        disabled={busy}
        className="bg-ink text-white rounded-lg px-5 py-2.5 text-sm font-semibold hover:opacity-90 disabled:opacity-50"
      >
        {busy ? "Sending…" : "Send message"}
      </button>
    </form>
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
