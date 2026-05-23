"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { api, auth } from "@/lib/api";

export default function AdminPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!auth.token()) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [router]);

  const { data: users, error, mutate } = useSWR(ready ? "admin-users" : null, () => api.adminUsers());
  const { data: messages } = useSWR(ready ? "admin-contact" : null, () => api.adminContact());

  // Non-admins get a 403 from the API → bounce them to the tenant dashboard.
  useEffect(() => {
    if (error) router.replace("/dashboard");
  }, [error, router]);

  if (!ready) return null;

  const toggle = async (u: any) => {
    if (u.is_admin) return;
    const action = u.disabled ? "Enable" : "Disable";
    if (!confirm(`${action} ${u.email}?`)) return;
    await api.adminSetUser(u.id, !u.disabled);
    mutate();
  };

  return (
    <div className="min-h-screen">
      <header className="border-b border-gray-200 bg-white">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Link href="/" className="text-lg font-bold text-ink">Mneme</Link>
            <span className="tag">Operator admin</span>
          </div>
          <Link href="/dashboard" className="text-sm text-gray-600 hover:text-ink">← Back to dashboard</Link>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-12">
        {/* Users */}
        <section>
          <h2 className="text-xl font-bold text-ink">Users</h2>
          <p className="text-sm text-gray-500 mb-4">All accounts, their workspace, plan, subscription, and status.</p>
          {!users ? (
            <p className="text-sm text-gray-500">Loading…</p>
          ) : (
            <div className="panel overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider text-gray-500 border-b border-gray-200">
                    <th className="px-4 py-3">User</th>
                    <th className="px-4 py-3">Workspace</th>
                    <th className="px-4 py-3">Plan</th>
                    <th className="px-4 py-3">Subscription</th>
                    <th className="px-4 py-3">Usage</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {users.map((u: any) => (
                    <tr key={u.id} className="border-b border-gray-100 last:border-0">
                      <td className="px-4 py-3">
                        <div className="font-semibold text-ink">
                          {u.name || "—"} {u.is_admin && <span className="tag ml-1">admin</span>}
                        </div>
                        <div className="text-gray-500 text-xs">{u.email}</div>
                      </td>
                      <td className="px-4 py-3 text-gray-700">{u.tenant_name || "—"}</td>
                      <td className="px-4 py-3"><span className="tag uppercase">{u.plan}</span></td>
                      <td className="px-4 py-3 text-gray-600">
                        {u.subscription_status || <span className="text-gray-400">none</span>}
                      </td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{u.agent_count} agents · {u.memory_count} mem</td>
                      <td className="px-4 py-3">
                        {u.disabled ? (
                          <span className="tag" style={{ background: "#fee2e2", color: "#991b1b" }}>disabled</span>
                        ) : (
                          <span className="tag" style={{ background: "#dcfce7", color: "#14532d" }}>active</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {!u.is_admin && (
                          <button
                            onClick={() => toggle(u)}
                            className={`text-xs font-semibold px-3 py-1.5 rounded border ${
                              u.disabled
                                ? "border-green-600 text-green-700 hover:bg-green-50"
                                : "border-red-500 text-red-600 hover:bg-red-50"
                            }`}
                          >
                            {u.disabled ? "Enable" : "Disable"}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* Contact messages */}
        <section>
          <h2 className="text-xl font-bold text-ink">Contact messages</h2>
          <p className="text-sm text-gray-500 mb-4">Submissions from the landing-page form (newest first).</p>
          {!messages ? (
            <p className="text-sm text-gray-500">Loading…</p>
          ) : messages.length === 0 ? (
            <div className="panel p-6 text-sm text-gray-500">No messages yet.</div>
          ) : (
            <div className="space-y-3">
              {messages.map((m: any) => (
                <div key={m.id} className="panel p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-semibold text-ink">
                      {m.name}{" "}
                      <span className="font-normal text-gray-500">
                        · <a className="text-accent hover:underline" href={`mailto:${m.email}`}>{m.email}</a>
                      </span>
                    </div>
                    <span className="text-[11px] text-gray-400 whitespace-nowrap">{new Date(m.created_at).toLocaleString()}</span>
                  </div>
                  <p className="mt-2 text-sm text-gray-700 whitespace-pre-wrap">{m.message}</p>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
