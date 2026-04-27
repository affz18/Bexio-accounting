-- Migration: erweitere pending_invoices.source-Constraint um 'imap'
-- Bisher liess der Check-Constraint nur 'telegram' zu. Mit dem
-- IMAP-Inbox-Connector schreiben wir jetzt auch source='imap'.
--
-- Im Supabase-SQL-Editor ausfuehren.

alter table public.pending_invoices
    drop constraint if exists pending_invoices_source_check;

alter table public.pending_invoices
    add constraint pending_invoices_source_check
    check (source in ('telegram', 'imap', 'email', 'webhook', 'manual'));
