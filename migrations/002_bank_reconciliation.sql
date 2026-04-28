-- Migration: Bank-Reconciliation (Phase 4)
--
-- Speichert geparste Bank-Bewegungen aus camt.054-Dateien sowie deren
-- Match-Vorschlaege gegen offene pending_invoices. Idempotent: dieselbe
-- bank-eindeutige TxId wird nur einmal aufgenommen.
--
-- Im Supabase-SQL-Editor ausfuehren.

-- ========================================================
-- BANK-TRANSAKTIONEN
-- ========================================================
-- Eine Zeile pro Bewegung aus dem camt.054 (Ntry > NtryDtls > TxDtls).
-- Outgoing (DBIT) hat negativen amount, Incoming (CRDT) positiv -
-- damit Bilanz-Logik (Summe = Saldo-Aenderung) trivial ist.

create table if not exists public.bank_transactions (
    id uuid primary key default gen_random_uuid(),
    tenant_id text not null default 'visioskin',

    -- Bank-Account (woher das camt kommt)
    bank_account_iban text,

    -- Eindeutige IDs aus camt
    transaction_id text,           -- AcctSvcrRef oder TxId
    end_to_end_id text,            -- E2E-ID, oft = QR-Ref
    structured_reference text,     -- CdtrRefInf/Ref - QR/ESR-27-Stellig

    -- Buchung
    booking_date date not null,
    value_date date,

    -- Betrag (signed: outgoing negativ, incoming positiv)
    amount numeric(14,2) not null,
    currency text not null default 'CHF',
    direction text not null check (direction in ('DBIT', 'CRDT')),

    -- Gegenpartei
    counterparty_name text,
    counterparty_iban text,

    -- Verwendungszweck
    remittance_unstructured text,  -- Ustrd freier Text

    -- Match-Status
    match_status text not null default 'unmatched'
        check (match_status in ('unmatched', 'proposed', 'matched', 'ignored')),

    -- Rohdaten zum Debuggen
    raw_xml_fragment text,

    -- Audit
    imported_at timestamptz not null default now(),
    matched_at timestamptz,

    -- Idempotenz: gleiche TxId pro Bank-Account nur einmal
    unique (tenant_id, bank_account_iban, transaction_id)
);

create index if not exists idx_bank_tx_match_status
    on public.bank_transactions (tenant_id, match_status, booking_date desc);

create index if not exists idx_bank_tx_qr_ref
    on public.bank_transactions (tenant_id, structured_reference)
    where structured_reference is not null;

create index if not exists idx_bank_tx_iban_amount
    on public.bank_transactions (tenant_id, counterparty_iban, amount)
    where counterparty_iban is not null;


-- ========================================================
-- PAYMENT-MATCHES
-- ========================================================
-- Verknuepft Bank-Transaktionen mit pending_invoices. Eine Bank-TX kann
-- mehrere Match-Vorschlaege haben (proposed); confirmed/booked nur einer.

create table if not exists public.payment_matches (
    id uuid primary key default gen_random_uuid(),
    tenant_id text not null default 'visioskin',

    bank_transaction_id uuid not null
        references public.bank_transactions(id) on delete cascade,
    pending_invoice_id uuid not null
        references public.pending_invoices(id) on delete cascade,

    -- Bexio-Feedback nach erfolgreicher Buchung
    bexio_payment_id text,
    bexio_bill_id text,

    -- Score & Strategie
    confidence numeric(4,3) not null
        check (confidence >= 0 and confidence <= 1),
    match_strategy text not null check (match_strategy in (
        'qr_reference',         -- QR-Ref exakt -> ~1.0
        'iban_amount_date',     -- IBAN + Betrag + Datum-Fenster
        'vendor_amount_date',   -- Vendor-Name fuzzy + Betrag + Datum
        'manual'                -- User hat manuell zugeordnet
    )),

    -- Status
    status text not null default 'proposed' check (status in (
        'proposed',     -- vom System vorgeschlagen, wartet auf User
        'confirmed',    -- User hat bestaetigt, noch nicht in Bexio
        'booked',       -- Erfolgreich als Payment in Bexio registriert
        'rejected',     -- User hat abgelehnt
        'failed'        -- Bexio-API-Fehler beim Buchen
    )),

    error_message text,

    created_at timestamptz not null default now(),
    confirmed_at timestamptz,
    booked_at timestamptz,

    -- Eine Bank-TX -> ein gebuchter Match
    unique (bank_transaction_id, pending_invoice_id)
);

create index if not exists idx_payment_matches_tx
    on public.payment_matches (bank_transaction_id, status);

create index if not exists idx_payment_matches_invoice
    on public.payment_matches (pending_invoice_id, status);

create index if not exists idx_payment_matches_status
    on public.payment_matches (tenant_id, status, created_at desc);
