import { createClient } from "@/lib/supabase/server";
import { redirect } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";

export default async function AuthedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  // Aktuellen Tenant aus user_tenants/tenants laden waere hier die Stelle.
  // In Phase B1 hat das System nur einen Tenant - hartcodiert "VisioSkin".
  // Block 1D macht das richtig: User -> Tenants Mapping + Switcher.
  const currentTenant = "VisioSkin";

  return (
    <div className="min-h-screen flex">
      <Sidebar userEmail={user.email ?? undefined} currentTenant={currentTenant} />
      <main className="flex-1 overflow-auto">
        <div className="max-w-6xl mx-auto px-8 py-8">
          {children}
        </div>
      </main>
    </div>
  );
}
