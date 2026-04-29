import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, FileText, ExternalLink, Download } from "lucide-react";
import { formatCHF, formatDate, statusVariant, cn } from "@/lib/utils";
import { getInvoiceById, getInvoiceFileUrl } from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function InvoiceDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const inv = await getInvoiceById(params.id);

  if (!inv) {
    notFound();
  }

  const fileUrl = await getInvoiceFileUrl(inv.file_path);
  const variant = statusVariant(inv.status);
  const isPdf =
    inv.file_mime_type?.includes("pdf") ||
    inv.original_filename?.toLowerCase().endsWith(".pdf");
  const isImage = inv.file_mime_type?.startsWith("image/");

  return (
    <div className="space-y-6">
      <Link
        href="/invoices"
        className="inline-flex items-center gap-1 text-sm text-foreground-muted hover:text-foreground"
      >
        <ArrowLeft className="w-3 h-3" /> Zurueck zu Belege
      </Link>

      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            {inv.vendor_name || "Unbekannter Lieferant"}
          </h1>
          {inv.invoice_number && (
            <p className="mt-1 text-foreground-muted font-mono text-sm">
              {inv.invoice_number}
            </p>
          )}
        </div>
        <span className={cn("badge", variant.className)}>{variant.label}</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* PDF / Image-Preview links */}
        <div className="lg:col-span-2 card overflow-hidden">
          <div className="px-6 py-4 border-b border-border flex items-center justify-between">
            <div className="font-medium truncate">
              {inv.original_filename || "Beleg"}
            </div>
            <div className="flex items-center gap-2">
              {fileUrl && (
                <a
                  href={fileUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="btn-ghost text-xs"
                >
                  <Download className="w-3 h-3" /> Original
                </a>
              )}
              {inv.bexio_bill_id && (
                <a
                  href={`https://office.bexio.com/index.php/kb_bill/show/id/${inv.bexio_bill_id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="btn-ghost text-xs"
                >
                  <ExternalLink className="w-3 h-3" /> In Bexio
                </a>
              )}
            </div>
          </div>

          {fileUrl && isPdf && (
            <iframe
              src={fileUrl}
              className="w-full"
              style={{ height: "70vh" }}
              title="Beleg PDF"
            />
          )}
          {fileUrl && isImage && (
            <div className="bg-background flex items-center justify-center">
              {/* Server-Component, kein next/image notwendig */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={fileUrl}
                alt={inv.original_filename || "Beleg"}
                className="max-h-[70vh] w-auto"
              />
            </div>
          )}
          {!fileUrl && (
            <div className="aspect-[3/4] bg-background flex items-center justify-center text-foreground-subtle">
              <div className="text-center">
                <FileText className="w-12 h-12 mx-auto" />
                <div className="mt-2 text-sm">Beleg nicht verfuegbar</div>
              </div>
            </div>
          )}
        </div>

        {/* Daten rechts */}
        <div className="space-y-4">
          <div className="card p-5">
            <h3 className="text-sm font-medium text-foreground-muted">Betrag</h3>
            <div className="mt-2 text-2xl font-semibold">
              {formatCHF(inv.total_amount)}
            </div>
            {inv.vat_amount !== null && inv.vat_rate !== null && (
              <div className="mt-1 text-xs text-foreground-muted">
                davon MwSt {inv.vat_rate}%: {formatCHF(inv.vat_amount)}
              </div>
            )}
          </div>

          <div className="card p-5 space-y-3 text-sm">
            <h3 className="font-medium">Buchungs-Details</h3>
            <DataRow
              label="Konto"
              value={
                inv.suggested_account_nr
                  ? `${inv.suggested_account_nr}${
                      inv.suggested_account_name
                        ? ` ${inv.suggested_account_name}`
                        : ""
                    }`
                  : "—"
              }
            />
            <DataRow label="MwSt-Code" value={inv.suggested_tax_code || "—"} />
            <DataRow label="Faellig" value={formatDate(inv.due_date)} />
            <DataRow
              label="Konfidenz"
              value={
                inv.confidence_score !== null
                  ? `${Math.round((inv.confidence_score || 0) * 100)}%`
                  : "—"
              }
            />
          </div>

          {(inv.iban || inv.reference_number || inv.uid_number) && (
            <div className="card p-5 space-y-3 text-sm">
              <h3 className="font-medium">Zahlungs-Info</h3>
              {inv.iban && <DataRow label="IBAN" value={inv.iban} mono />}
              {inv.reference_number && (
                <DataRow
                  label="QR-Ref"
                  value={`…${inv.reference_number.slice(-7)}`}
                  mono
                />
              )}
              {inv.uid_number && (
                <DataRow label="UID-Nr" value={inv.uid_number} mono />
              )}
            </div>
          )}

          <div className="card p-5 space-y-3 text-sm">
            <h3 className="font-medium">Quelle</h3>
            <DataRow
              label="Eingang"
              value={
                inv.source === "imap"
                  ? "Mail-Inbox"
                  : inv.source === "telegram"
                  ? "Telegram"
                  : inv.source || "—"
              }
            />
            <DataRow label="Erfasst" value={formatDate(inv.created_at)} />
            {inv.bexio_booked_at && (
              <DataRow
                label="In Bexio gebucht"
                value={formatDate(inv.bexio_booked_at)}
              />
            )}
          </div>

          {inv.error_message && (
            <div className="card p-5 border-danger/50">
              <h3 className="font-medium text-danger">Fehler</h3>
              <p className="mt-1 text-sm text-foreground-muted break-words">
                {inv.error_message}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DataRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-foreground-muted shrink-0">{label}</span>
      <span
        className={cn("text-right truncate", mono && "font-mono text-xs")}
        title={value}
      >
        {value}
      </span>
    </div>
  );
}
