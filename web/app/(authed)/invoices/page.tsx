import Link from "next/link";
import { Search, Filter } from "lucide-react";
import { formatCHF, formatDate, statusVariant, cn } from "@/lib/utils";

// MOCK
const MOCK_INVOICES = [
  { id: "1", vendor_name: "SwissPlakat AG", invoice_number: "INV-2026-001", total_amount: 659.40, invoice_date: "2026-04-25", due_date: "2026-05-25", status: "booked" },
  { id: "2", vendor_name: "Swisscom (Schweiz) AG", invoice_number: "8475-29371", total_amount: 89.00, invoice_date: "2026-04-22", due_date: "2026-05-22", status: "booked" },
  { id: "3", vendor_name: "Aesthetikoase Landa", invoice_number: "RE2026-04637", total_amount: 918.85, invoice_date: "2026-04-20", due_date: "2026-05-20", status: "awaiting_approval" },
  { id: "4", vendor_name: "Migros", invoice_number: "—", total_amount: 47.30, invoice_date: "2026-04-18", due_date: null, status: "booked_private" },
  { id: "5", vendor_name: "Hostpoint AG", invoice_number: "IN-2026-1882", total_amount: 204.00, invoice_date: "2026-04-15", due_date: "2026-05-15", status: "booked" },
  { id: "6", vendor_name: "Wagner Roger", invoice_number: "KA-00212", total_amount: 0, invoice_date: "2026-03-17", due_date: null, status: "rejected" },
];

export default function InvoicesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Belege</h1>
        <p className="mt-1 text-foreground-muted">
          Alle empfangenen Belege - aus Mailbox und Telegram.
        </p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-foreground-subtle" />
          <input
            type="text"
            placeholder="Suche nach Lieferant oder Nummer…"
            className="input pl-9"
            disabled
          />
        </div>
        <button className="btn-secondary text-sm" disabled>
          <Filter className="w-4 h-4" />
          Status: Alle
        </button>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-background border-b border-border">
            <tr className="text-left text-foreground-muted text-xs uppercase tracking-wide">
              <th className="px-6 py-3 font-medium">Lieferant</th>
              <th className="px-6 py-3 font-medium">Nummer</th>
              <th className="px-6 py-3 font-medium">Datum</th>
              <th className="px-6 py-3 font-medium">Faellig</th>
              <th className="px-6 py-3 font-medium text-right">Betrag</th>
              <th className="px-6 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {MOCK_INVOICES.map((inv) => {
              const variant = statusVariant(inv.status);
              return (
                <tr key={inv.id} className="hover:bg-background">
                  <td className="px-6 py-3">
                    <Link href={`/invoices/${inv.id}`} className="font-medium hover:underline">
                      {inv.vendor_name}
                    </Link>
                  </td>
                  <td className="px-6 py-3 text-foreground-muted text-xs font-mono">
                    {inv.invoice_number}
                  </td>
                  <td className="px-6 py-3 text-foreground-muted">
                    {formatDate(inv.invoice_date)}
                  </td>
                  <td className="px-6 py-3 text-foreground-muted">
                    {formatDate(inv.due_date)}
                  </td>
                  <td className="px-6 py-3 text-right font-medium">
                    {inv.status === "rejected" ? "—" : formatCHF(inv.total_amount)}
                  </td>
                  <td className="px-6 py-3">
                    <span className={cn("badge", variant.className)}>
                      {variant.label}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="text-xs text-foreground-muted text-center">
        Mock-Daten. Live-Anbindung via Supabase folgt in Block 1D.
      </div>
    </div>
  );
}
