import Link from "next/link";
import { ArrowRight, FileText, Banknote, AlertCircle } from "lucide-react";
import { StatCard } from "@/components/StatCard";
import { formatCHF, formatDate, statusVariant, cn } from "@/lib/utils";
import { getInvoiceStats, getRecentInvoices } from "@/lib/queries";

// Server Component - laedt direkt im Render
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function DashboardPage() {
  const [stats, recent] = await Promise.all([
    getInvoiceStats(),
    getRecentInvoices(undefined, 8),
  ]);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Dashboard</h1>
        <p className="mt-1 text-foreground-muted">
          Uebersicht aller Belege und automatisierten Buchungen.
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard
          label="Belege diesen Monat"
          value={stats.totalThisMonth}
          sublabel={
            stats.totalAmountThisMonth > 0
              ? formatCHF(stats.totalAmountThisMonth)
              : "noch keine Buchungen"
          }
        />
        <StatCard
          label="Wartet auf Freigabe"
          value={stats.awaitingApproval}
          sublabel={
            stats.awaitingApproval > 0
              ? "braucht deine Aufmerksamkeit"
              : "alles erledigt"
          }
          trend={stats.awaitingApproval > 0 ? "down" : "up"}
        />
        <StatCard
          label="Gebucht"
          value={stats.bookedThisMonth + stats.bookedPrivateThisMonth}
          sublabel={
            stats.bookedPrivateThisMonth > 0
              ? `${stats.bookedThisMonth} regulaer + ${stats.bookedPrivateThisMonth} privat`
              : "vollautomatisch"
          }
          trend="up"
        />
        <StatCard
          label="Fehler"
          value={stats.failed}
          sublabel={stats.failed > 0 ? "Pruefen empfohlen" : "alles glatt"}
          trend={stats.failed > 0 ? "down" : "flat"}
        />
      </div>

      {/* Quick-Actions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <ActionCard
          icon={<AlertCircle className="w-5 h-5" />}
          title={
            stats.awaitingApproval > 0
              ? `${stats.awaitingApproval} Belege warten auf Freigabe`
              : "Keine offenen Freigaben"
          }
          description={
            stats.awaitingApproval > 0
              ? "Vorschlaege pruefen und bestaetigen."
              : "Sobald Belege reinkommen, erscheinen sie hier."
          }
          href="/invoices?status=awaiting_approval"
          urgent={stats.awaitingApproval > 0}
        />
        <ActionCard
          icon={<Banknote className="w-5 h-5" />}
          title="Bank-Abgleich"
          description="camt-Datei hochladen und Zahlungen matchen."
          href="/reconciliation"
        />
        <ActionCard
          icon={<FileText className="w-5 h-5" />}
          title="MwSt-Bericht"
          description="Vorsteuer-Report fuer das aktuelle Quartal."
          href="/reports/mwst"
        />
      </div>

      {/* Recent Invoices */}
      <div className="card">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h2 className="font-semibold">Letzte Belege</h2>
          <Link
            href="/invoices"
            className="text-sm text-foreground-muted hover:text-foreground inline-flex items-center gap-1"
          >
            Alle anzeigen <ArrowRight className="w-3 h-3" />
          </Link>
        </div>

        {recent.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="divide-y divide-border">
            {recent.map((inv) => {
              const variant = statusVariant(inv.status);
              return (
                <Link
                  key={inv.id}
                  href={`/invoices/${inv.id}`}
                  className="flex items-center px-6 py-3 hover:bg-background"
                >
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">
                      {inv.vendor_name || "Unbekannter Lieferant"}
                    </div>
                    <div className="text-xs text-foreground-muted">
                      {formatDate(inv.invoice_date) !== "—"
                        ? formatDate(inv.invoice_date)
                        : `Eingang ${formatDate(inv.created_at)}`}
                    </div>
                  </div>
                  <div className="text-right mr-4">
                    <div className="font-medium">
                      {formatCHF(inv.total_amount)}
                    </div>
                  </div>
                  <span className={cn("badge", variant.className)}>
                    {variant.label}
                  </span>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function ActionCard({
  icon,
  title,
  description,
  href,
  urgent,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  href: string;
  urgent?: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "card p-5 hover:border-border-strong transition-colors block",
        urgent && "border-warning/50",
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "w-10 h-10 rounded-lg flex items-center justify-center shrink-0",
            urgent ? "bg-warning/10 text-warning" : "bg-primary/5 text-primary",
          )}
        >
          {icon}
        </div>
        <div className="min-w-0">
          <div className="font-medium">{title}</div>
          <div className="mt-1 text-sm text-foreground-muted">{description}</div>
        </div>
      </div>
    </Link>
  );
}

function EmptyState() {
  return (
    <div className="px-6 py-12 text-center">
      <FileText className="w-10 h-10 mx-auto text-foreground-subtle" />
      <h3 className="mt-3 font-medium">Noch keine Belege</h3>
      <p className="mt-1 text-sm text-foreground-muted max-w-sm mx-auto">
        Sobald Rechnungen per Mail oder Telegram reinkommen, erscheinen sie hier.
        Pruefe die Mailbox-Verbindung in den Einstellungen.
      </p>
      <Link href="/settings" className="btn-secondary text-sm mt-4 inline-flex">
        Zu den Einstellungen
      </Link>
    </div>
  );
}
