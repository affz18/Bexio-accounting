import Link from "next/link";
import { ArrowRight, FileText, Banknote, AlertCircle, CheckCircle2 } from "lucide-react";
import { StatCard } from "@/components/StatCard";
import { formatCHF, formatDate, statusVariant, cn } from "@/lib/utils";

// MOCK-DATEN - Block 1D wird das aus Supabase ziehen.
const MOCK_STATS = {
  totalThisMonth: 47,
  awaitingApproval: 4,
  bookedThisMonth: 41,
  failed: 2,
  totalAmountThisMonth: 18420.50,
};

const MOCK_RECENT = [
  { id: "1", vendor_name: "SwissPlakat AG", total_amount: 659.40, invoice_date: "2026-04-25", status: "booked" },
  { id: "2", vendor_name: "Swisscom (Schweiz) AG", total_amount: 89.00, invoice_date: "2026-04-22", status: "booked" },
  { id: "3", vendor_name: "Aesthetikoase Landa", total_amount: 918.85, invoice_date: "2026-04-20", status: "awaiting_approval" },
  { id: "4", vendor_name: "Migros", total_amount: 47.30, invoice_date: "2026-04-18", status: "booked_private" },
  { id: "5", vendor_name: "Hostpoint AG", total_amount: 204.00, invoice_date: "2026-04-15", status: "booked" },
];

export default function DashboardPage() {
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
          value={MOCK_STATS.totalThisMonth}
          sublabel={formatCHF(MOCK_STATS.totalAmountThisMonth)}
        />
        <StatCard
          label="Wartet auf Freigabe"
          value={MOCK_STATS.awaitingApproval}
          sublabel="braucht deine Aufmerksamkeit"
          trend={MOCK_STATS.awaitingApproval > 0 ? "down" : "up"}
        />
        <StatCard
          label="Gebucht"
          value={MOCK_STATS.bookedThisMonth}
          sublabel="vollautomatisch"
          trend="up"
        />
        <StatCard
          label="Fehler"
          value={MOCK_STATS.failed}
          sublabel="Pruefen empfohlen"
          trend={MOCK_STATS.failed > 0 ? "down" : "flat"}
        />
      </div>

      {/* Quick-Actions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <ActionCard
          icon={<AlertCircle className="w-5 h-5" />}
          title={`${MOCK_STATS.awaitingApproval} Belege warten auf Freigabe`}
          description="Vorschlaege pruefen und bestaetigen."
          href="/invoices?filter=awaiting_approval"
          urgent={MOCK_STATS.awaitingApproval > 0}
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
          <Link href="/invoices" className="text-sm text-foreground-muted hover:text-foreground inline-flex items-center gap-1">
            Alle anzeigen <ArrowRight className="w-3 h-3" />
          </Link>
        </div>
        <div className="divide-y divide-border">
          {MOCK_RECENT.map((inv) => {
            const variant = statusVariant(inv.status);
            return (
              <Link
                key={inv.id}
                href={`/invoices/${inv.id}`}
                className="flex items-center px-6 py-3 hover:bg-background"
              >
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate">{inv.vendor_name}</div>
                  <div className="text-xs text-foreground-muted">{formatDate(inv.invoice_date)}</div>
                </div>
                <div className="text-right mr-4">
                  <div className="font-medium">{formatCHF(inv.total_amount)}</div>
                </div>
                <span className={cn("badge", variant.className)}>{variant.label}</span>
              </Link>
            );
          })}
        </div>
      </div>

      <div className="text-xs text-foreground-muted text-center">
        Daten sind Mock-Beispiele. In Block 1D wird live aus Supabase geladen.
      </div>
    </div>
  );
}

function ActionCard({
  icon, title, description, href, urgent,
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
        <div className={cn(
          "w-10 h-10 rounded-lg flex items-center justify-center shrink-0",
          urgent ? "bg-warning/10 text-warning" : "bg-primary/5 text-primary",
        )}>
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
