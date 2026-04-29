# Bexio AI Workspace - Web UI

Web-Dashboard fuer den Bexio-AI-Agent. Funktioniert fuer einzelne Firmen
(1 Mandat) genauso wie fuer Treuhaender (n Mandanten). Zeigt **echte Daten**
direkt aus Supabase.

---

## ⚡ Schnell-Start fuer Demo (15 Minuten)

Wenn du das deinem Vater oder Treuhaender zeigen willst, hier der direkte Weg.

### Variante A: Lokal auf deinem Laptop

```bash
cd web
npm install                  # 1-2 Min
cp .env.example .env.local
# .env.local oeffnen und 3 Werte eintragen (siehe unten)
npm run dev                  # Startet auf http://localhost:3000
```

Dann im Browser `http://localhost:3000` oeffnen, registrieren, und du siehst
deine echten VisioSkin-Belege. Auf einem Mac kannst du den Laptop einfach
mitnehmen.

### Variante B: Auf Vercel deployen (kostenlos, oeffentlich erreichbar)

Ideal wenn du willst dass dein Vater die URL einfach auf seinem Computer aufruft.

1. **Repo auf GitHub bringen** (du hast das schon)
2. **Vercel** → "New Project" → dein Github-Repo
3. **Root Directory** auf `web` setzen (sehr wichtig - sonst sucht Vercel die Next.js-App im Root)
4. **Environment Variables** eintragen:
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `NEXT_PUBLIC_SUPABASE_STORAGE_BUCKET=invoices`
5. **Deploy** klicken

Nach 1-2 Min ist die App online unter `https://<dein-projekt>.vercel.app`.

Eigene Domain spaeter (z.B. `bexio.deinedomain.ch`) - geht in Vercel mit
einem Klick + DNS-Eintrag.

---

## 🔑 ENV-Variablen die du brauchst

Drei Werte aus deinem Supabase-Projekt:

1. **`NEXT_PUBLIC_SUPABASE_URL`**
   - Im Supabase-Dashboard: Settings → API → "Project URL"
   - Format: `https://xxxxxxx.supabase.co`

2. **`NEXT_PUBLIC_SUPABASE_ANON_KEY`**
   - Settings → API → "anon public" Key
   - Beginnt mit `eyJhbGciOi...`

3. **`SUPABASE_SERVICE_ROLE_KEY`**
   - Settings → API → "service_role" Key
   - **GEHEIM** - nie ins Frontend, nie in Git
   - Beginnt mit `eyJhbGciOi...` (laenger als anon-key)

Tipp: In deinem Python-Bot (Railway-Variables) steht `SUPABASE_SERVICE_ROLE_KEY`
schon - einfach kopieren.

---

## 👀 Was dein Vater / die Treuhaenderin sieht

Wenn er die App oeffnet (Login als VisioSkin-User), sieht er:

1. **Dashboard** (`/dashboard`)
   - 4 Stat-Cards: Belege diesen Monat, Wartet auf Freigabe, Gebucht, Fehler
   - 3 Quick-Action-Cards: Freigaben, Bank-Abgleich, MwSt-Bericht
   - Liste der letzten 8 Belege
2. **Belege** (`/invoices`)
   - Volle Liste aller je verarbeiteten Belege
   - Filter: Alle / Wartet / Gebucht / Privat / Fehler
   - Suche nach Lieferantenname oder Rechnungsnummer
   - Klick → Detail-Seite mit PDF-Preview
3. **Beleg-Detail** (`/invoices/<id>`)
   - PDF / Foto direkt im Browser angezeigt
   - Vollstaendige extrahierte Daten (Lieferant, Betrag, MwSt, IBAN, QR-Ref, etc.)
   - Konto-Vorschlag mit Konfidenz-Score
   - Direkt-Link zur Rechnung in Bexio
4. **Lieferanten** (`/vendors`)
   - Was der Bot ueber jeden Lieferanten gelernt hat
   - Standard-Konto, MwSt, Anzahl Buchungen, Konfidenz
5. **Mandanten** (`/tenants`)
   - Liste aller Bexio-Mandate (Treuhaender-View)
   - Status: Bexio-verbunden, Mail-Inbox aktiv

### Demo-Drehbuch (5 Min Vorfuehrung)

Optimal so reden:

> "Schau, hier sind alle Lieferanten-Rechnungen die letzten 30 Tage reinkamen.
> Eingang per Mail oder Telegram - der Bot extrahiert sie automatisch und
> schlaegt das richtige Konto vor."

Auf einen Beleg klicken:

> "Hier siehst du den Original-Beleg, links das PDF, rechts was die KI
> extrahiert hat - Lieferant, Betrag, MwSt, alles automatisch.
> Wenn das stimmt, ein Klick und die Rechnung ist in Bexio gebucht."

Auf Lieferanten klicken:

> "Und hier siehst du was der Bot lernt: bei Swisscom 24x auf Konto 6510 -
> deshalb schlaegt er das beim 25. Mal automatisch vor mit 95% Konfidenz.
> Eure Buchhalterin muss es nur noch durchwinken."

---

## 🛠 Architektur

```
web/
├── app/
│   ├── layout.tsx              # Root-Layout
│   ├── page.tsx                # Landing-Page (oeffentlich)
│   ├── login/page.tsx          # Auth (Login + Signup)
│   ├── globals.css             # Tailwind + Component-Klassen
│   └── (authed)/               # Auth-required Routes
│       ├── layout.tsx          # Sidebar + Auth-Check
│       ├── dashboard/          # Uebersicht
│       ├── invoices/           # Belege-Liste + Detail
│       ├── reconciliation/     # Bank-Abgleich (Stub)
│       ├── vendors/            # Gelernte Lieferanten
│       ├── tenants/            # Mandanten-Verwaltung
│       └── settings/           # Konfiguration (Stub)
├── components/                 # UI-Components
├── lib/
│   ├── supabase/
│   │   ├── client.ts           # Browser-Client (Auth)
│   │   ├── server.ts           # Server-Client (Auth)
│   │   └── admin.ts            # Service-Role-Client (Reads)
│   ├── queries.ts              # Server-Queries
│   ├── types.ts                # TS-Types matching Supabase
│   └── utils.ts                # cn(), formatCHF(), etc.
└── middleware.ts               # Auth-Redirect-Logik
```

### Wie Daten geladen werden

- **Auth (Login/Signup):** Supabase Auth ueber Anon-Key + Cookies
- **Reads (Dashboard, Belege, etc.):** Server-Components rufen
  `lib/queries.ts` auf, das wiederum den Service-Role-Client nutzt
- **Storage-PDFs:** signed URLs vom Service-Role-Client (10 Min gueltig)

Service-Role bypassed RLS - das ist OK fuer Demo + Single-Tenant. Sobald
mehrere Tenants live sind: RLS aktivieren und auf Anon-Client umstellen
(Block 1C der Roadmap).

---

## 🗺 Roadmap

| Block | Was | Status |
|---|---|---|
| **1A** | Scaffold (Pages, Auth, Sidebar) | ✅ done |
| **1B** | Live-Daten aus Supabase | ✅ done (heute) |
| 1C | RLS + Tenant-Switcher | offen |
| 1D | Onboarding (Bexio verbinden, IMAP) | offen |
| 1E | Interaktive Aktionen (Buchen-Klick im Web) | offen |
| 1F | Bexio OAuth | offen |

---

## 🚀 Deployment-Plan (final)

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

**Heute schon machbar:**
- Web-App auf Vercel (kostenlos)
- Bot weiterhin auf Railway (laeuft)
- Beide zur gleichen Supabase-DB
- Beleg per Mail/Telegram → vom Bot verarbeitet → in DB → in Web sofort sichtbar

**Eigene Domain:** in Vercel → Settings → Domains → `app.deinedomain.ch`
hinzufuegen, dann CNAME-Eintrag bei deinem DNS-Provider setzen.
