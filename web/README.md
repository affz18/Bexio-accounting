# Bexio AI Workspace - Web UI

Next.js-basiertes Dashboard fuer den Bexio-AI-Agent. Funktioniert fuer
einzelne Firmen (1 Mandat) genauso wie fuer Treuhaender (n Mandanten).

## Aktueller Stand (Block 1A der UI - Phase B)

- Next.js 14 App Router + TypeScript + Tailwind
- Supabase Auth (Login, Signup)
- Routing-Struktur fertig: Dashboard, Belege, Bank-Abgleich, Lieferanten,
  Mandanten, Einstellungen
- Sidebar-Navigation
- **Alle Seiten zeigen Mock-Daten.** Live-Daten aus Supabase folgt in
  Block 1B (siehe Roadmap unten).

## Setup lokal

```bash
cd web
npm install
cp .env.example .env.local
# .env.local bearbeiten: SUPABASE_URL und SUPABASE_ANON_KEY eintragen
npm run dev
```

Dann auf `http://localhost:3000` oeffnen.

## ENV-Variablen

| Variable | Was |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Selbe Supabase wie der Python-Bot |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | **anon-key** (NICHT service-role) |
| `NEXT_PUBLIC_APP_NAME` | Optional. Display-Name in Header. |

Die Web-App nutzt nur den anon-key + Row-Level-Security. Der service-role
bleibt im Python-Bot fuer privilegierte Operationen.

## Architektur

```
web/
├── app/
│   ├── layout.tsx          # Root-Layout
│   ├── page.tsx            # Landing-Page (oeffentlich)
│   ├── login/page.tsx      # Auth (Login + Signup)
│   ├── globals.css         # Tailwind + Component-Klassen
│   └── (authed)/           # Auth-required Routes
│       ├── layout.tsx      # Sidebar + Auth-Check
│       ├── dashboard/      # Uebersicht
│       ├── invoices/       # Belege-Liste + Detail
│       ├── reconciliation/ # Bank-Abgleich
│       ├── vendors/        # Gelernte Lieferanten
│       ├── tenants/        # Mandanten-Verwaltung
│       └── settings/       # Konfiguration
├── components/             # Wiederverwendbare UI
│   ├── Sidebar.tsx
│   └── StatCard.tsx
├── lib/
│   ├── supabase/
│   │   ├── client.ts       # Browser-Client
│   │   └── server.ts       # Server-Client (mit Cookies)
│   └── utils.ts            # cn(), formatCHF(), etc.
└── middleware.ts           # Auth-Redirect-Logik
```

## Roadmap

### Block 1A (jetzt) — Scaffold
- [x] Next.js Projekt-Setup
- [x] Tailwind + Design-Tokens
- [x] Supabase Auth (Login/Signup)
- [x] Sidebar-Navigation
- [x] Alle Seiten mit Mock-Daten
- [x] Landing-Page

### Block 1B — Live-Daten
- [ ] Supabase-Queries fuer pending_invoices in Dashboard + Liste
- [ ] PDF-Preview aus Supabase Storage
- [ ] Vendors-Live-Daten
- [ ] Stats live aggregiert

### Block 1C — RLS + Tenant-Auth
- [ ] Supabase RLS-Policies fuer Multi-Tenant
- [ ] user_tenants Junction-Table
- [ ] Tenant-Switcher in Sidebar (Treuhaender-Use-Case)
- [ ] Korrektes Tenant-Filtering ueberall

### Block 1D — Onboarding
- [ ] Signup -> Tenant erstellen-Flow
- [ ] Bexio API-Token einrichten (in DB)
- [ ] IMAP-Credentials einrichten
- [ ] Test-Verbindung Bexio + Mailbox

### Block 1E — Interaktive Aktionen
- [ ] Beleg im Web bestaetigen / verwerfen
- [ ] camt-Datei-Upload via Drag&Drop
- [ ] Bank-Match-Approval direkt im Web
- [ ] Settings live editierbar

### Block 1F — Bexio OAuth
- [ ] OAuth-Flow gegen Bexio statt Personal-Access-Token
- [ ] Token-Refresh-Handling
- [ ] Marketplace-App-Voraussetzung pruefen

## Deployment-Idee

Vercel fuer das Frontend (kostenlos, schnell, optimiert fuer Next.js).
Python-Bot weiter auf Railway. Beide gegen die gleiche Supabase-DB.

```
+---------------------+         +-----------------+
|    Vercel           |         |   Railway       |
|    web/ (Next.js)   |         |   app/ (Bot)    |
+---------+-----------+         +--------+--------+
          |                              |
          +--------> Supabase <----------+
                    (Auth + DB + Storage)
                              |
                              v
                    +-------------------+
                    |  Bexio API        |
                    |  Gemini API       |
                    |  IMAP-Server      |
                    +-------------------+
```
