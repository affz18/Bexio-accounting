import Link from "next/link";
import { Plus, ExternalLink, CheckCircle2, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

// MOCK - Treuhaender-Use-Case mit mehreren Mandanten
const MOCK_TENANTS = [
  {
    id: "visioskin",
    display_name: "VisioSkin",
    company_name: "VisioSkin Solutions GmbH",
    is_active: true,
    bexio_connected: true,
    imap_enabled: true,
    pending_count: 4,
  },
  {
    id: "demo-handwerk",
    display_name: "Demo Handwerk AG",
    company_name: "Demo Handwerk AG",
    is_active: false,
    bexio_connected: false,
    imap_enabled: false,
    pending_count: 0,
  },
];

export default function TenantsPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Mandanten</h1>
          <p className="mt-1 text-foreground-muted">
            Alle deine Bexio-Mandate. Wechsle hier zwischen ihnen oder lege einen neuen an.
          </p>
        </div>
        <button className="btn-primary text-sm" disabled>
          <Plus className="w-4 h-4" />
          Neuer Mandant
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {MOCK_TENANTS.map((t) => (
          <div key={t.id} className={cn(
            "card p-6",
            !t.is_active && "opacity-60",
          )}>
            <div className="flex items-start justify-between">
              <div>
                <h3 className="font-semibold text-lg">{t.display_name}</h3>
                <p className="text-sm text-foreground-muted">{t.company_name}</p>
              </div>
              {t.is_active && t.pending_count > 0 && (
                <span className="badge bg-warning/10 text-warning">
                  {t.pending_count} offen
                </span>
              )}
            </div>

            <div className="mt-4 space-y-2 text-sm">
              <ConfigRow
                label="Bexio verbunden"
                ok={t.bexio_connected}
              />
              <ConfigRow
                label="Mail-Inbox aktiv"
                ok={t.imap_enabled}
              />
            </div>

            <div className="mt-5 flex items-center gap-2">
              <button
                className={cn(
                  "btn text-sm flex-1",
                  t.is_active ? "btn-secondary" : "btn-primary",
                )}
                disabled
              >
                {t.is_active ? "Aktiv" : "Aktivieren"}
              </button>
              <Link
                href={`/settings?tenant=${t.id}`}
                className="btn-ghost text-sm"
              >
                Einstellungen
              </Link>
            </div>
          </div>
        ))}

        {/* Add-Mandant-Card */}
        <button
          className="card p-6 border-dashed flex flex-col items-center justify-center gap-2 text-foreground-muted hover:border-border-strong hover:text-foreground transition-colors min-h-[200px]"
          disabled
        >
          <Plus className="w-6 h-6" />
          <span className="text-sm font-medium">Neuen Mandanten hinzufuegen</span>
          <span className="text-xs">Bexio verbinden, Mailbox einrichten, los.</span>
        </button>
      </div>

      <div className="text-xs text-foreground-muted text-center">
        Multi-Mandant ist in Block 1D voll funktional - heute Mock-View.
      </div>
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
      <span className={cn(ok ? "" : "text-foreground-muted")}>
        {label}
      </span>
    </div>
  );
}
