"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/api";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [tenant, setTenant] = useState<any>(null);
  const [user, setUser] = useState<any>(null);

  useEffect(() => {
    const t = auth.token();
    if (!t) {
      router.replace("/");
      return;
    }
    setTenant(auth.tenant());
    setUser(auth.user());
    setReady(true);
  }, [router]);

  if (!ready) return null;

  const logout = () => {
    auth.clear();
    router.push("/");
  };

  return (
    <div className="min-h-screen">
      <header className="bg-ink text-white px-6 py-3 flex items-center justify-between">
        <div className="flex items-baseline gap-3">
          <span className="text-lg font-bold">Mneme</span>
          <span className="text-[11px] uppercase tracking-widest opacity-70">{tenant?.name}</span>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <span className="opacity-80">{user?.email}</span>
          <button onClick={logout} className="opacity-80 hover:opacity-100">Sign out</button>
        </div>
      </header>
      <main className="p-6 max-w-7xl mx-auto">{children}</main>
    </div>
  );
}
