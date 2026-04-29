import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Tailwind-Class-Merger fuer conditional classes ohne Konflikte. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Schweizer CHF-Format mit Apostroph als Tausender-Trennzeichen. */
export function formatCHF(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "—";
  return new Intl.NumberFormat("de-CH", {
    style: "currency",
    currency: "CHF",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

/** YYYY-MM-DD -> z.B. "27. Apr. 2026" */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("de-CH", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

/** Status-Badge-Farben aus pending_invoices.status */
export function statusVariant(status: string | null | undefined): {
  label: string;
  className: string;
} {
  switch ((status || "").toLowerCase()) {
    case "booked":
      return { label: "Gebucht", className: "bg-success/10 text-success" };
    case "booked_private":
      return { label: "Privat bezahlt", className: "bg-success/10 text-success" };
    case "awaiting_approval":
    case "extracted":
      return { label: "Wartet auf Freigabe", className: "bg-warning/10 text-warning" };
    case "pending":
      return { label: "In Bearbeitung", className: "bg-foreground-muted/10 text-foreground-muted" };
    case "failed":
      return { label: "Fehler", className: "bg-danger/10 text-danger" };
    case "rejected":
    case "not_invoice":
      return { label: "Verworfen", className: "bg-foreground-muted/10 text-foreground-muted" };
    default:
      return { label: status || "—", className: "bg-foreground-muted/10 text-foreground-muted" };
  }
}
