import { formatCHF, formatDate, cn } from "@/lib/utils";

const MOCK_VENDORS = [
  { id: "1", name: "Swisscom (Schweiz) AG", account: "6510 Kommunikation", booking_count: 24, confidence: 0.95, last_booked_at: "2026-04-22" },
  { id: "2", name: "Migros", account: "6500 Bueromaterial", booking_count: 18, confidence: 0.85, last_booked_at: "2026-04-18" },
  { id: "3", name: "Hostpoint AG", account: "6512 Internet", booking_count: 12, confidence: 0.80, last_booked_at: "2026-04-15" },
  { id: "4", name: "SwissPlakat AG", account: "6600 Werbung", booking_count: 3, confidence: 0.65, last_booked_at: "2026-04-25" },
  { id: "5", name: "Aesthetikoase Landa", account: "—", booking_count: 0, confidence: 0, last_booked_at: null },
];

export default function VendorsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Lieferanten</h1>
        <p className="mt-1 text-foreground-muted">
          Was der Bot gelernt hat - pro Lieferant das Konto und MwSt.
        </p>
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-background border-b border-border">
            <tr className="text-left text-foreground-muted text-xs uppercase tracking-wide">
              <th className="px-6 py-3 font-medium">Lieferant</th>
              <th className="px-6 py-3 font-medium">Standard-Konto</th>
              <th className="px-6 py-3 font-medium text-center">Buchungen</th>
              <th className="px-6 py-3 font-medium text-center">Konfidenz</th>
              <th className="px-6 py-3 font-medium">Zuletzt gebucht</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {MOCK_VENDORS.map((v) => {
              const confColor =
                v.confidence >= 0.8 ? "text-success" :
                v.confidence >= 0.5 ? "text-warning" :
                "text-foreground-muted";
              return (
                <tr key={v.id} className="hover:bg-background">
                  <td className="px-6 py-3 font-medium">{v.name}</td>
                  <td className="px-6 py-3 text-foreground-muted text-xs">
                    {v.account}
                  </td>
                  <td className="px-6 py-3 text-center text-foreground-muted">
                    {v.booking_count}
                  </td>
                  <td className={cn("px-6 py-3 text-center font-medium", confColor)}>
                    {v.confidence > 0 ? `${Math.round(v.confidence * 100)}%` : "—"}
                  </td>
                  <td className="px-6 py-3 text-foreground-muted">
                    {formatDate(v.last_booked_at)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
