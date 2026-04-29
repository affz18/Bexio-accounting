/**
 * TypeScript-Types die zur Supabase-Schema passen.
 * Wenn das Schema sich aendert, hier nachfuehren.
 */

export type InvoiceStatus =
  | "pending"
  | "extracted"
  | "awaiting_approval"
  | "booked"
  | "booked_private"
  | "failed"
  | "rejected"
  | "not_invoice";

export interface PendingInvoice {
  id: string;
  tenant_id: string;
  source: string | null;
  source_reference: string | null;
  file_path: string | null;
  original_filename: string | null;
  file_size_bytes: number | null;
  file_mime_type: string | null;
  status: InvoiceStatus | string;
  vendor_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  total_amount: number | null;
  vat_amount: number | null;
  vat_rate: number | null;
  currency: string | null;
  iban: string | null;
  reference_number: string | null;
  uid_number: string | null;
  bexio_bill_id: string | null;
  bexio_booked_at: string | null;
  suggested_account_id: number | null;
  suggested_account_nr: string | null;
  suggested_account_name: string | null;
  suggested_tax_id: number | null;
  suggested_tax_code: string | null;
  confidence_score: number | null;
  error_message: string | null;
  extracted_data: Record<string, unknown> | null;
  created_at: string;
  updated_at: string | null;
}

export interface VendorMemory {
  id: string;
  tenant_id: string;
  name: string;
  normalized_name: string;
  bexio_contact_id: number | null;
  default_account_id: number | null;
  default_account_nr: string | null;
  default_tax_id: number | null;
  default_tax_rate: number | null;
  iban: string | null;
  uid_nummer: string | null;
  booking_count: number;
  confidence_score: number;
  last_booked_at: string | null;
  created_at: string;
}

export interface Tenant {
  id: string;
  display_name: string;
  bexio_api_token: string | null;
  bexio_company_id: string | null;
  imap_enabled: boolean;
  imap_host: string | null;
  imap_user: string | null;
  imap_folder: string | null;
  telegram_notify_chat_id: number | null;
  private_payment_credit_account_nr: string | null;
  company_name: string | null;
  company_uid: string | null;
  is_active: boolean;
  created_at: string;
}

export interface InvoiceStats {
  totalThisMonth: number;
  awaitingApproval: number;
  bookedThisMonth: number;
  bookedPrivateThisMonth: number;
  failed: number;
  totalAmountThisMonth: number;
  totalAll: number;
}

export interface VendorWithAccount extends VendorMemory {
  account_label: string | null;
}
