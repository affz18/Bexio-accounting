"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, FileText, Banknote, Settings, Users, LogOut, Receipt,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { createClient } from "@/lib/supabase/client";
import { useRouter } from "next/navigation";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/invoices", label: "Belege", icon: FileText },
  { href: "/reconciliation", label: "Bank-Abgleich", icon: Banknote },
  { href: "/vendors", label: "Lieferanten", icon: Receipt },
  { href: "/tenants", label: "Mandanten", icon: Users },
  { href: "/settings", label: "Einstellungen", icon: Settings },
];

export function Sidebar({
  userEmail,
  currentTenant,
}: {
  userEmail?: string;
  currentTenant?: string;
}) {
  const pathname = usePathname();
  const router = useRouter();

  async function logout() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <aside className="w-60 bg-background-card border-r border-border flex flex-col">
      <div className="p-6 border-b border-border">
        <div className="font-semibold tracking-tight">Bexio AI Workspace</div>
        {currentTenant && (
          <Link
            href="/tenants"
            className="mt-3 inline-flex items-center gap-2 text-xs text-foreground-muted hover:text-foreground"
          >
            <span className="w-2 h-2 rounded-full bg-success" />
            {currentTenant}
          </Link>
        )}
      </div>

      <nav className="flex-1 p-3 space-y-1">
        {NAV.map((item) => {
          const active = pathname === item.href || pathname.startsWith(item.href + "/");
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-md text-sm",
                active
                  ? "bg-primary text-primary-fg"
                  : "text-foreground-muted hover:bg-background hover:text-foreground",
              )}
            >
              <Icon className="w-4 h-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="p-3 border-t border-border">
        {userEmail && (
          <div className="px-3 py-2 text-xs text-foreground-muted truncate">
            {userEmail}
          </div>
        )}
        <button
          onClick={logout}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm text-foreground-muted hover:bg-background hover:text-foreground"
        >
          <LogOut className="w-4 h-4" />
          Abmelden
        </button>
      </div>
    </aside>
  );
}
