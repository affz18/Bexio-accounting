-- Migration: Multi-Tenant Foundation (Phase B1)
--
-- Bereitet die DB fuer Multi-Tenant vor. Erstellt eine `tenants`-Tabelle
-- und ergaenzt `tenant_id` auf allen bestehenden Datentabellen (sofern
-- noch nicht vorhanden - bank_transactions und payment_matches haben es
-- schon aus Migration 002).
--
-- Existierende Daten werden mit tenant_id='visioskin' (default) befuellt.
-- Spaeter koennen wir hier RLS aktivieren - vorerst nur Schema, keine
-- Permission-Aenderungen.
--
-- Im Supabase-SQL-Editor ausfuehren NACH 002_bank_reconciliation.sql.

-- ========================================================
-- TENANTS-TABELLE
-- ========================================================
-- text-PK damit slugs ('visioskin', 'klein-ag') statt UUIDs verwendet
-- werden koennen. Konsistent mit Phase 4 wo tenant_id bereits text ist.

create table if not exists public.tenants (
    id text primary key,
    display_name text not null,

    -- Bexio-Anbindung (per-Tenant)
    -- HINWEIS: in Phase B1 noch leer - die Werte stehen weiterhin in Env.
    -- Block 1B migriert dann von Env zu DB und macht das verschluesselt.
    bexio_api_token text,
    bexio_company_id text,

    -- IMAP-Anbindung (per-Tenant)
    imap_enabled boolean not null default false,
    imap_host text,
    imap_port integer default 993,
    imap_user text,
    imap_password text,
    imap_folder text default 'INBOX',
    imap_keywords_regex text,

    -- Notification-Channel (Telegram heute, Teams/Email spaeter)
    telegram_notify_chat_id bigint,

    -- Privat-bezahlt-Default
    private_payment_credit_account_nr text default '2100',

    -- Empfaenger-Validierung (fuer Phase Recipient-Check)
    company_name text,
    company_uid text,           -- CHE-XXX.XXX.XXX
    company_name_aliases text,  -- Komma-separiert, fuer fuzzy-Match

    -- Lifecycle
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_tenants_active
    on public.tenants (is_active)
    where is_active = true;

-- Default-Tenant einsetzen. Idempotent dank ON CONFLICT.
insert into public.tenants (id, display_name, company_name, is_active)
values ('visioskin', 'VisioSkin', 'VisioSkin', true)
on conflict (id) do nothing;


-- ========================================================
-- TENANT_ID AUF BESTEHENDE TABELLEN ERGAENZEN
-- ========================================================
-- Pattern: ADD COLUMN IF NOT EXISTS mit Default 'visioskin'.
-- Damit ist die Migration idempotent und alte Zeilen kriegen automatisch
-- den Default.

-- pending_invoices
alter table public.pending_invoices
    add column if not exists tenant_id text not null default 'visioskin';

create index if not exists idx_pending_invoices_tenant_status
    on public.pending_invoices (tenant_id, status, created_at desc);

-- vendors
alter table public.vendors
    add column if not exists tenant_id text not null default 'visioskin';

create index if not exists idx_vendors_tenant
    on public.vendors (tenant_id, normalized_name);

-- account_mappings (Bexio-Kontenplan-Cache)
alter table public.account_mappings
    add column if not exists tenant_id text not null default 'visioskin';

create index if not exists idx_account_mappings_tenant_nr
    on public.account_mappings (tenant_id, account_nr);

-- tax_mappings (Bexio-MwSt-Codes-Cache)
alter table public.tax_mappings
    add column if not exists tenant_id text not null default 'visioskin';

create index if not exists idx_tax_mappings_tenant
    on public.tax_mappings (tenant_id, tax_type);

-- processed_emails (IMAP-Idempotenz)
alter table public.processed_emails
    add column if not exists tenant_id text not null default 'visioskin';

create index if not exists idx_processed_emails_tenant
    on public.processed_emails (tenant_id, processed_at desc);

-- invoice_log (Audit-Trail)
alter table public.invoice_log
    add column if not exists tenant_id text not null default 'visioskin';

create index if not exists idx_invoice_log_tenant_at
    on public.invoice_log (tenant_id, created_at desc);

-- authorized_users
alter table public.authorized_users
    add column if not exists tenant_id text not null default 'visioskin';

create index if not exists idx_authorized_users_tenant_chat
    on public.authorized_users (tenant_id, telegram_chat_id);


-- ========================================================
-- FOREIGN-KEY-CONSTRAINTS
-- ========================================================
-- tenant_id -> tenants(id) auf allen Tabellen. Wir nehmen "ON DELETE
-- RESTRICT" damit man einen Tenant nicht aus Versehen mit Daten loeschen
-- kann. Cascade-Loeschen muss explizit ausgeloest werden.
--
-- Idempotent: wir droppen die alten constraints (falls vorhanden) und
-- setzen sie frisch.

-- pending_invoices
alter table public.pending_invoices
    drop constraint if exists pending_invoices_tenant_id_fkey;
alter table public.pending_invoices
    add constraint pending_invoices_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict;

-- vendors
alter table public.vendors
    drop constraint if exists vendors_tenant_id_fkey;
alter table public.vendors
    add constraint vendors_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict;

-- account_mappings
alter table public.account_mappings
    drop constraint if exists account_mappings_tenant_id_fkey;
alter table public.account_mappings
    add constraint account_mappings_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict;

-- tax_mappings
alter table public.tax_mappings
    drop constraint if exists tax_mappings_tenant_id_fkey;
alter table public.tax_mappings
    add constraint tax_mappings_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict;

-- processed_emails
alter table public.processed_emails
    drop constraint if exists processed_emails_tenant_id_fkey;
alter table public.processed_emails
    add constraint processed_emails_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict;

-- invoice_log
alter table public.invoice_log
    drop constraint if exists invoice_log_tenant_id_fkey;
alter table public.invoice_log
    add constraint invoice_log_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict;

-- authorized_users
alter table public.authorized_users
    drop constraint if exists authorized_users_tenant_id_fkey;
alter table public.authorized_users
    add constraint authorized_users_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict;

-- bank_transactions (hat bereits tenant_id aus 002, jetzt mit FK)
alter table public.bank_transactions
    drop constraint if exists bank_transactions_tenant_id_fkey;
alter table public.bank_transactions
    add constraint bank_transactions_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict;

-- payment_matches (hat bereits tenant_id aus 002, jetzt mit FK)
alter table public.payment_matches
    drop constraint if exists payment_matches_tenant_id_fkey;
alter table public.payment_matches
    add constraint payment_matches_tenant_id_fkey
    foreign key (tenant_id) references public.tenants(id) on delete restrict;


-- ========================================================
-- UNIQUE-CONSTRAINTS PRO TENANT ANPASSEN
-- ========================================================
-- Bestehende UNIQUE-Indexe muessen tenant_id einbeziehen, damit zwei
-- Tenants z.B. den gleichen Vendor-Namen oder die gleiche IMAP-UID
-- haben koennen.

-- vendors.normalized_name war global eindeutig - jetzt pro Tenant
alter table public.vendors
    drop constraint if exists vendors_normalized_name_key;
do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'vendors_tenant_normalized_name_key'
    ) then
        alter table public.vendors
            add constraint vendors_tenant_normalized_name_key
            unique (tenant_id, normalized_name);
    end if;
end $$;

-- account_mappings.bexio_account_id pro Tenant eindeutig
alter table public.account_mappings
    drop constraint if exists account_mappings_bexio_account_id_key;
do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'account_mappings_tenant_bexio_id_key'
    ) then
        alter table public.account_mappings
            add constraint account_mappings_tenant_bexio_id_key
            unique (tenant_id, bexio_account_id);
    end if;
end $$;

-- tax_mappings.bexio_tax_id pro Tenant eindeutig
alter table public.tax_mappings
    drop constraint if exists tax_mappings_bexio_tax_id_key;
do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'tax_mappings_tenant_bexio_id_key'
    ) then
        alter table public.tax_mappings
            add constraint tax_mappings_tenant_bexio_id_key
            unique (tenant_id, bexio_tax_id);
    end if;
end $$;

-- processed_emails.uid war pro (account, folder, uid) eindeutig - jetzt
-- zusaetzlich pro Tenant (eigentlich impliziert ueber account, aber wir
-- machen es explizit damit die Index-Reihenfolge fuer Queries optimal ist)
alter table public.processed_emails
    drop constraint if exists processed_emails_account_folder_uid_key;
do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'processed_emails_tenant_account_folder_uid_key'
    ) then
        alter table public.processed_emails
            add constraint processed_emails_tenant_account_folder_uid_key
            unique (tenant_id, account, folder, uid);
    end if;
end $$;

-- authorized_users.telegram_chat_id war global eindeutig - jetzt pro Tenant
alter table public.authorized_users
    drop constraint if exists authorized_users_telegram_chat_id_key;
do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'authorized_users_tenant_telegram_chat_id_key'
    ) then
        alter table public.authorized_users
            add constraint authorized_users_tenant_telegram_chat_id_key
            unique (tenant_id, telegram_chat_id);
    end if;
end $$;


-- ========================================================
-- FERTIG
-- ========================================================
-- Nach dieser Migration:
-- - tenants-Tabelle existiert mit Default 'visioskin'
-- - Alle Daten-Tabellen haben tenant_id mit FK
-- - UNIQUE-Constraints sind tenant-aware
-- - Bestehende Daten gehoeren automatisch zu 'visioskin'
--
-- NICHT geaendert in dieser Migration (kommt in Block 1B / Code-Refactor):
-- - Code ignoriert tenant_id noch beim Lesen/Schreiben (nimmt einfach default)
-- - Bexio/IMAP-Credentials stehen weiterhin in Env, nicht in tenants
-- - Keine RLS-Policies aktiviert
