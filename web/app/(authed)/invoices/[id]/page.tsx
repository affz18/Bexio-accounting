import Link from "next/link";
import { ArrowLeft, FileText, ExternalLink, Download } from "lucide-react";
import { formatCHF, formatDate, statusVariant, cn } from "@/lib/utils";

// MOCK
const MOCK_INVOICE = {
  id: "1",
  vendor_name: "SwissPlakat AG",
  invoice_number: "INV-2026-001",
  invoice_date: "2026-04-25",
  due_date: "2026-05-25",
  total_amount: 659.40,
  vat_amount: 49.49,
  vat_rate: 8.1,
  currency: "CHF",
  iban: "CH4800024024C9300062H",
  reference_number: "210000000003139471430009017",
  uid_number: "CHE-123.456.789",
  status: "booked",
  bexio_bill_id: "8dda7fac-0a7b-411d-b5a4-191dbe6eb84e",
  source: "telegram",
  suggested_account_nr: "6500",
  suggested_account_name: "Bueromaterial",
  suggested_tax_code: "VSTN",
};

export default function InvoiceDetailPage({ params }: { params: { id: string } }) {
  const inv = MOCK_INVOICE;
  const variant = statusVariant(inv.status);

  return (
    <div className="space-y-6">
      <Link
        href="/invoices"
        className="inline-flex items-center gap-1 text-sm text-foreground-muted hover:text-foreground"
      >
        <ArrowLeft className="w-3 h-3" /> Zurueck zu Belege
      </Link>

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{inv.vendor_name}</h1>
          <p className="mt-1 text-foreground-muted font-mono text-sm">
            {inv.invoice_number}
          </p>
        </div>
        <span className={cn("badge", variant.className)}>{variant.label}</span>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* PDF-Preview links */}
        <div className="col-span-2 card overflow-hidden">
          <div className="px-6 py-4 border-b border-border flex items-center justify-between">
            <div className="font-medium">Beleg</div>
            <div className="flex items-center gap-2">
              <button className="btn-ghost text-xs">
                <Download className="w-3 h-3" /> Original
              </button>
              <Link
                href={`https://bexio.com/bills/${inv.bexio_bill_id}`}
                target="_blank"
                className="btn-ghost text-xs"
              >
                <ExternalLink className="w-3 h-3" /> In Bexio
              </Link>
            </div>
          </div>
          <div className="aspect-[3/4] bg-background flex items-center justify-center text-foreground-subtle">
            <div className="text-center">
              <FileText className="w-12 h-12 mx-auto" />
              <div className="mt-2 text-sm">PDF-Preview</div>
              <div className="text-xs">In Block 1D direkt aus Supabase Storage</div>
            </div>
          </div>
        </div>

        {/* Daten rechts */}
        <div className="space-y-4">
          <div className="card p-5">
            <h3 className="text-sm font-medium text-foreground-muted">Betrag</h3>
            <div className="mt-2 text-2xl font-semibold">
              {formatCHF(inv.total_amount)}
            </div>
            <div className="mt-1 text-xs text-foreground-muted">
              davon MwSt {inv.vat_rate}%: {formatCHF(inv.vat_amount)}
            </div>
          </div>

          <div className="card p-5 space-y-3 text-sm">
            <h3 className="font-medium">Buchungs-Details</h3>
            <DataRow label="Konto" value={`${inv.suggested_account_nr} ${inv.suggested_account_name}`} />
            <DataRow label="MwSt-Code" value={inv.suggested_tax_code} />
            <DataRow label="Faellig" value={formatDate(inv.due_date)} />
          </div>

          <div className="card p-5 space-y-3 text-sm">
            <h3 className="font-medium">Zahlungs-Info</h3>
            <DataRow label="IBAN" value={inv.iban} mono />
            <DataRow label="QR-Ref" value={inv.reference_number ? `…${inv.reference_number.slice(-7)}` : "—"} mono />
            <DataRow label="UID-Nr" value={inv.uid_number} mono />
          </div>

          <div className="card p-5 space-y-3 text-sm">
            <h3 className="font-medium">Quelle</h3>
            <DataRow label="Eingang" value={inv.source === "imap" ? "Mail-Inbox" : inv.source === "telegram" ? "Telegram" : inv.source} />
          </div>
        </div>
      </div>
    </div>
  );
}

function DataRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-foreground-muted">{label}</span>
      <span className={cn("text-right truncate", mono && "font-mono text-xs")}>{value}</span>
    </div>
  );
}
