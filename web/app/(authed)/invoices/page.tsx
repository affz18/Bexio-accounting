import Link from "next/link";
import { Search, FileText } from "lucide-react";
import { formatCHF, formatDate, statusVariant, cn } from "@/lib/utils";
import { listInvoices } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const STATUS_FILTERS = [
  { value: "", label: "Alle" },
  { value: "awaiting_approval", label: "Wartet" },
  { value: "extracted", label: "Wartet" },
  { value: "booked", label: "Gebucht" },
  { value: "booked_private", label: "Privat" },
  { value: "failed", label: "Fehler" },
];

export default async function InvoicesPage({
  searchParams,
}: {
  searchParams: { status?: string; q?: string };
}) {
  const status = searchParams.status || "";
  const search = searchParams.q || "";

  const invoices = await listInvoices({
    status: status || undefined,
    search: search || undefined,
    limit: 200,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Belege</h1>
        <p className="mt-1 text-foreground-muted">
          Alle empfangenen Belege - aus Mailbox und Telegram.
        </p>
      </div>

      {/* Filters */}
      <form className="flex items-center gap-3 flex-wrap" action="/invoices">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-foreground-subtle" />
          <input
            type="text"
            name="q"
            placeholder="Suche nach Lieferant oder Nummer…"
            className="input pl-9"
            defaultValue={search}
          />
        </div>
        <div className="flex items-center gap-1">
          {STATUS_FILTERS.filter(
            (f, i, arr) => arr.findIndex((a) => a.label === f.label) === i,
          ).map((f) => {
            const isActive =
              (f.value === "" && !status) ||
              status === f.value ||
              (f.label === "Wartet" &&
                ["awaiting_approval", "extracted"].includes(status));
            const href = f.value
              ? `/invoices?status=${f.value}${search ? `&q=${encodeURIComponent(search)}` : ""}`
              : `/invoices${search ? `?q=${encodeURIComponent(search)}` : ""}`;
            return (
              <Link
                key={f.label}
                href={href}
                className={cn(
                  "px-3 py-1.5 rounded-md text-sm transition-colors",
                  isActive
                    ? "bg-primary text-primary-fg"
                    : "text-foreground-muted hover:bg-background-card hover:text-foreground",
                )}
              >
                {f.label}
              </Link>
            );
          })}
        </div>
      </form>

      {/* Table */}
      {invoices.length === 0 ? (
        <div className="card py-16 text-center">
          <FileText className="w-10 h-10 mx-auto text-foreground-subtle" />
          <h3 className="mt-3 font-medium">
            {search || status ? "Keine Treffer" : "Noch keine Belege"}
          </h3>
          <p className="mt-1 text-sm text-foreground-muted">
            {search || status
              ? "Versuche andere Filter oder Suche."
              : "Schicke einen Beleg per Telegram oder konfiguriere die Mailbox."}
          </p>
        </div>
      ) : (
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
              {invoices.map((inv) => {
                const variant = statusVariant(inv.status);
                return (
                  <tr key={inv.id} className="hover:bg-background">
                    <td className="px-6 py-3">
                      <Link
                        href={`/invoices/${inv.id}`}
                        className="font-medium hover:underline"
                      >
                        {inv.vendor_name || "—"}
                      </Link>
                    </td>
                    <td className="px-6 py-3 text-foreground-muted text-xs font-mono">
                      {inv.invoice_number || "—"}
                    </td>
                    <td className="px-6 py-3 text-foreground-muted">
                      {formatDate(inv.invoice_date)}
                    </td>
                    <td className="px-6 py-3 text-foreground-muted">
                      {formatDate(inv.due_date)}
                    </td>
                    <td className="px-6 py-3 text-right font-medium">
                      {formatCHF(inv.total_amount)}
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
          <div className="px-6 py-3 text-xs text-foreground-muted bg-background border-t border-border">
            {invoices.length} Belege
          </div>
        </div>
      )}
    </div>
  );
}
