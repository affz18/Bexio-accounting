-- Migration: processed_emails Table
-- Fuer Idempotenz des IMAP-Inbox-Scans. Speichert welche (account, folder, uid)
-- bereits verarbeitet wurde, damit Bot-Restarts oder Polling-Overlap keine
-- Doppel-Verarbeitung ausloesen.
--
-- Im Supabase-SQL-Editor ausfuehren.

create table if not exists public.processed_emails (
    id uuid primary key default gen_random_uuid(),
    account text not null default '',
    folder text not null default 'INBOX',
    uid text not null,
    status text not null check (status in ('filtered', 'processed', 'failed', 'no_attachment')),
    invoice_id uuid references public.pending_invoices(id) on delete set null,
    subject text,
    from_address text,
    error text,
    processed_at timestamptz not null default now(),
    unique (account, folder, uid)
);

create index if not exists idx_processed_emails_account_folder
    on public.processed_emails (account, folder, processed_at desc);

create index if not exists idx_processed_emails_invoice
    on public.processed_emails (invoice_id)
    where invoice_id is not null;
