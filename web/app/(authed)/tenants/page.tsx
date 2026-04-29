import Link from "next/link";
import { Plus, Building2, CheckCircle2, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { listTenants } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function TenantsPage() {
  const tenants = await listTenants();

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Mandanten</h1>
          <p className="mt-1 text-foreground-muted">
            Alle deine Bexio-Mandate. Wechsle zwischen ihnen oder lege einen
            neuen an.
          </p>
        </div>
        <button className="btn-primary text-sm" disabled>
          <Plus className="w-4 h-4" />
          Neuer Mandant
        </button>
      </div>

      {tenants.length === 0 ? (
        <div className="card py-16 text-center">
          <Building2 className="w-10 h-10 mx-auto text-foreground-subtle" />
          <h3 className="mt-3 font-medium">Noch keine Mandanten</h3>
          <p className="mt-1 text-sm text-foreground-muted">
            Fuehre die Migration 003_multi_tenant.sql in Supabase aus.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {tenants.map((t) => {
            const bexioConnected = !!t.bexio_api_token;
            const imapEnabled = t.imap_enabled;
            return (
              <div
                key={t.id}
                className={cn("card p-6", !t.is_active && "opacity-60")}
              >
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="font-semibold text-lg">{t.display_name}</h3>
                    <p className="text-sm text-foreground-muted">
                      {t.company_name || t.id}
                    </p>
                  </div>
                  <span
                    className={cn(
                      "badge",
                      t.is_active
                        ? "bg-success/10 text-success"
                        : "bg-foreground-muted/10 text-foreground-muted",
                    )}
                  >
                    {t.is_active ? "Aktiv" : "Inaktiv"}
                  </span>
                </div>

                <div className="mt-4 space-y-2 text-sm">
                  <ConfigRow label="Bexio verbunden" ok={bexioConnected} />
                  <ConfigRow label="Mail-Inbox aktiv" ok={imapEnabled} />
                </div>

                <div className="mt-5 flex items-center gap-2">
                  <Link
                    href={`/settings?tenant=${t.id}`}
                    className="btn-secondary text-sm"
                  >
                    Einstellungen
                  </Link>
                  <Link
                    href={`/invoices?tenant=${t.id}`}
                    className="btn-ghost text-sm"
                  >
                    Belege
                  </Link>
                </div>
              </div>
            );
          })}

          <button
            className="card p-6 border-dashed flex flex-col items-center justify-center gap-2 text-foreground-muted hover:border-border-strong hover:text-foreground transition-colors min-h-[200px]"
            disabled
          >
            <Plus className="w-6 h-6" />
            <span className="text-sm font-medium">
              Neuen Mandanten hinzufuegen
            </span>
            <span className="text-xs">
              Bexio verbinden, Mailbox einrichten, los.
            </span>
          </button>
        </div>
      )}
    </div>
  );
}

function ConfigRow({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div className="flex items-center gap-2">
      {ok ? (
        <CheckCircle2 className="w-4 h-4 text-success" />
      ) : (
        <AlertCircle className="w-4 h-4 text-warning" />
      )}
      <span className={cn(ok ? "" : "text-foreground-muted")}>{label}</span>
    </div>
  );
}
