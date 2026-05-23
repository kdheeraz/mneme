"use client";
import useSWR from "swr";
import Link from "next/link";
import { api } from "@/lib/api";

export default function PricingSection() {
  const { data: plans } = useSWR("public-plans", () => api.publicPlans());

  if (!plans) return <p className="text-center text-sm text-gray-500">Loading plans…</p>;

  return (
    <div className="grid gap-5 sm:grid-cols-3 items-stretch">
      {plans.map((p: any) => {
        const featured = p.key === "pro";
        return (
          <div
            key={p.key}
            className={`panel p-6 flex flex-col ${featured ? "border-ink ring-1 ring-ink/10 relative" : ""}`}
          >
            {featured && (
              <span className="absolute -top-3 left-6 tag !bg-ink !text-white">Most popular</span>
            )}
            <h3 className="text-lg font-bold text-ink">{p.name}</h3>
            <div className="mt-2 text-3xl font-extrabold text-ink">
              {p.amount === 0 ? "Free" : `₹${(p.amount / 100).toLocaleString("en-IN")}`}
              {p.amount > 0 && <span className="text-sm font-normal text-gray-500">/mo</span>}
            </div>
            <ul className="mt-5 space-y-2 text-sm text-gray-600 flex-1">
              <li className="flex gap-2">
                <span className="text-accent">✓</span>
                {p.limits.agents.toLocaleString("en-IN")} agent{p.limits.agents === 1 ? "" : "s"}
              </li>
              <li className="flex gap-2">
                <span className="text-accent">✓</span>
                {p.limits.memories.toLocaleString("en-IN")} memories
              </li>
              <li className="flex gap-2">
                <span className="text-accent">✓</span>
                Hybrid search, graph &amp; reconciliation
              </li>
              <li className="flex gap-2">
                <span className="text-accent">✓</span>
                Python &amp; JS SDKs, REST API
              </li>
            </ul>
            <Link
              href="/login"
              className={`mt-6 text-center rounded-lg px-4 py-2.5 text-sm font-semibold ${
                featured ? "bg-ink text-white hover:opacity-90" : "border border-gray-300 hover:bg-gray-50"
              }`}
            >
              {p.key === "free" ? "Start free" : `Choose ${p.name}`}
            </Link>
          </div>
        );
      })}
    </div>
  );
}
