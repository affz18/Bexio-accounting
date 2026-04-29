import { Receipt } from "lucide-react";
import { formatDate, cn } from "@/lib/utils";
import { listVendors } from "@/lib/queries";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function VendorsPage() {
  const vendors = await listVendors();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Lieferanten</h1>
        <p className="mt-1 text-foreground-muted">
          Was der Bot gelernt hat - pro Lieferant das Konto und die MwSt.
        </p>
      </div>

      {vendors.length === 0 ? (
        <div className="card py-16 text-center">
          <Receipt className="w-10 h-10 mx-auto text-foreground-subtle" />
          <h3 className="mt-3 font-medium">Noch keine Lieferanten gelernt</h3>
          <p className="mt-1 text-sm text-foreground-muted max-w-md mx-auto">
            Sobald du Belege buchst oder einmal /learn im Telegram-Bot ausfuehrst
            (zieht aus deiner Bexio-History), erscheinen die Lieferanten hier.
          </p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-background border-b border-border">
              <tr className="text-left text-foreground-muted text-xs uppercase tracking-wide">
                <th className="px-6 py-3 font-medium">Lieferant</th>
                <th className="px-6 py-3 font-medium">Standard-Konto</th>
                <th className="px-6 py-3 font-medium">MwSt</th>
                <th className="px-6 py-3 font-medium text-center">Buchungen</th>
                <th className="px-6 py-3 font-medium text-center">Konfidenz</th>
                <th className="px-6 py-3 font-medium">Zuletzt gebucht</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {vendors.map((v) => {
                const conf = Number(v.confidence_score) || 0;
                const confColor =
                  conf >= 0.8
                    ? "text-success"
                    : conf >= 0.5
                    ? "text-warning"
                    : "text-foreground-muted";
                return (
                  <tr key={v.id} className="hover:bg-background">
                    <td className="px-6 py-3 font-medium">{v.name}</td>
                    <td className="px-6 py-3 text-foreground-muted text-xs">
                      {v.default_account_nr || "—"}
                    </td>
                    <td className="px-6 py-3 text-foreground-muted text-xs">
                      {v.default_tax_rate !== null
                        ? `${v.default_tax_rate}%`
                        : "—"}
                    </td>
                    <td className="px-6 py-3 text-center text-foreground-muted">
                      {v.booking_count}
                    </td>
                    <td
                      className={cn(
                        "px-6 py-3 text-center font-medium",
                        confColor,
                      )}
                    >
                      {conf > 0 ? `${Math.round(conf * 100)}%` : "—"}
                    </td>
                    <td className="px-6 py-3 text-foreground-muted">
                      {formatDate(v.last_booked_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="px-6 py-3 text-xs text-foreground-muted bg-background border-t border-border">
            {vendors.length} Lieferanten
          </div>
        </div>
      )}
    </div>
  );
}
