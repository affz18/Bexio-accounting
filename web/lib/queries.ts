import "server-only";

import { createAdminClient } from "./supabase/admin";
import type {
  PendingInvoice,
  VendorMemory,
  Tenant,
  InvoiceStats,
} from "./types";

/**
 * Server-Queries gegen Supabase - laufen NUR im Server (RSC, Server-Actions,
 * Route-Handlers). Fuer Phase B nutzen wir den Service-Role-Client direkt;
 * Multi-Tenant-Filterung passiert per tenant_id-Parameter.
 *
 * Wenn DB nicht erreichbar / leer ist, geben Funktionen einen sinnvollen
 * Default zurueck (leere Liste, Null-Stats), damit die UI immer rendert
 * ohne Crash. Logging via console.error - sichtbar in Vercel-Logs.
 */

export const DEFAULT_TENANT_ID = "visioskin";

function getMonthRange(): { start: string; end: string } {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), 1);
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 0, 23, 59, 59);
  return {
    start: start.toISOString(),
    end: end.toISOString(),
  };
}

export async function getInvoiceStats(
  tenantId: string = DEFAULT_TENANT_ID,
): Promise<InvoiceStats> {
  const empty: InvoiceStats = {
    totalThisMonth: 0,
    awaitingApproval: 0,
    bookedThisMonth: 0,
    bookedPrivateThisMonth: 0,
    failed: 0,
    totalAmountThisMonth: 0,
    totalAll: 0,
  };

  try {
    const supabase = createAdminClient();
    const { start, end } = getMonthRange();

    const [thisMonth, allOfTime] = await Promise.all([
      supabase
        .from("pending_invoices")
        .select("status,total_amount")
        .eq("tenant_id", tenantId)
        .gte("created_at", start)
        .lte("created_at", end),
      supabase
        .from("pending_invoices")
        .select("id", { count: "exact", head: true })
        .eq("tenant_id", tenantId),
    ]);

    const monthRows = (thisMonth.data ?? []) as Array<{
      status: string;
      total_amount: number | null;
    }>;

    const stats: InvoiceStats = {
      totalThisMonth: monthRows.length,
      awaitingApproval: monthRows.filter(
        (r) => r.status === "extracted" || r.status === "awaiting_approval",
      ).length,
      bookedThisMonth: monthRows.filter((r) => r.status === "booked").length,
      bookedPrivateThisMonth: monthRows.filter(
        (r) => r.status === "booked_private",
      ).length,
      failed: monthRows.filter((r) => r.status === "failed").length,
      totalAmountThisMonth: monthRows.reduce(
        (sum, r) => sum + (Number(r.total_amount) || 0),
        0,
      ),
      totalAll: allOfTime.count ?? 0,
    };
    return stats;
  } catch (e) {
    console.error("getInvoiceStats failed", e);
    return empty;
  }
}

export async function getRecentInvoices(
  tenantId: string = DEFAULT_TENANT_ID,
  limit = 10,
): Promise<PendingInvoice[]> {
  try {
    const supabase = createAdminClient();
    const { data, error } = await supabase
      .from("pending_invoices")
      .select("*")
      .eq("tenant_id", tenantId)
      .order("created_at", { ascending: false })
      .limit(limit);
    if (error) throw error;
    return (data ?? []) as PendingInvoice[];
  } catch (e) {
    console.error("getRecentInvoices failed", e);
    return [];
  }
}

export interface ListInvoicesOptions {
  tenantId?: string;
  status?: string;
  search?: string;
  limit?: number;
}

export async function listInvoices(
  options: ListInvoicesOptions = {},
): Promise<PendingInvoice[]> {
  const tenantId = options.tenantId ?? DEFAULT_TENANT_ID;
  const limit = options.limit ?? 100;
  try {
    const supabase = createAdminClient();
    let query = supabase
      .from("pending_invoices")
      .select("*")
      .eq("tenant_id", tenantId)
      .order("invoice_date", { ascending: false, nullsFirst: false })
      .order("created_at", { ascending: false })
      .limit(limit);

    if (options.status) {
      query = query.eq("status", options.status);
    }
    if (options.search) {
      query = query.or(
        `vendor_name.ilike.%${options.search}%,invoice_number.ilike.%${options.search}%`,
      );
    }
    const { data, error } = await query;
    if (error) throw error;
    return (data ?? []) as PendingInvoice[];
  } catch (e) {
    console.error("listInvoices failed", e);
    return [];
  }
}

export async function getInvoiceById(
  id: string,
  tenantId: string = DEFAULT_TENANT_ID,
): Promise<PendingInvoice | null> {
  try {
    const supabase = createAdminClient();
    const { data, error } = await supabase
      .from("pending_invoices")
      .select("*")
      .eq("id", id)
      .eq("tenant_id", tenantId)
      .maybeSingle();
    if (error) throw error;
    return (data as PendingInvoice) ?? null;
  } catch (e) {
    console.error("getInvoiceById failed", e);
    return null;
  }
}

/**
 * Generiert eine signed URL fuer einen Beleg im Supabase Storage.
 * Falls Storage-Bucket fehlt oder File nicht existiert: null.
 */
export async function getInvoiceFileUrl(
  filePath: string | null,
  expiresInSeconds = 60 * 10,
): Promise<string | null> {
  if (!filePath) return null;
  try {
    const supabase = createAdminClient();
    const bucket =
      process.env.NEXT_PUBLIC_SUPABASE_STORAGE_BUCKET ?? "invoices";
    const { data, error } = await supabase.storage
      .from(bucket)
      .createSignedUrl(filePath, expiresInSeconds);
    if (error) throw error;
    return data?.signedUrl ?? null;
  } catch (e) {
    console.error("getInvoiceFileUrl failed", e);
    return null;
  }
}

export async function listVendors(
  tenantId: string = DEFAULT_TENANT_ID,
  limit = 100,
): Promise<VendorMemory[]> {
  try {
    const supabase = createAdminClient();
    const { data, error } = await supabase
      .from("vendors")
      .select("*")
      .eq("tenant_id", tenantId)
      .order("last_booked_at", { ascending: false, nullsFirst: false })
      .limit(limit);
    if (error) throw error;
    return (data ?? []) as VendorMemory[];
  } catch (e) {
    console.error("listVendors failed", e);
    return [];
  }
}

export async function listTenants(): Promise<Tenant[]> {
  try {
    const supabase = createAdminClient();
    const { data, error } = await supabase
      .from("tenants")
      .select("*")
      .eq("is_active", true)
      .order("display_name");
    if (error) throw error;
    return (data ?? []) as Tenant[];
  } catch (e) {
    console.error("listTenants failed", e);
    return [];
  }
}

/**
 * Kombiniert Vendor mit lesbarem Account-Label fuer die UI.
 * (Vermeidet eine zweite Query pro Vendor - account_nr ist bereits drin.)
 */
export async function listVendorsWithAccountLabel(
  tenantId: string = DEFAULT_TENANT_ID,
  limit = 100,
) {
  const vendors = await listVendors(tenantId, limit);
  return vendors.map((v) => ({
    ...v,
    account_label: v.default_account_nr
      ? `${v.default_account_nr}${v.default_account_id ? "" : ""}`
      : null,
  }));
}
