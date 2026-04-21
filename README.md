# VisioSkin Accounting Agent

Telegram-Bot der Rechnungen automatisch via Gemini analysiert und in Bexio verbucht.

## Features

- 📄 PDF/Bild-Upload via Telegram
- 🧠 Automatische Extraktion via Gemini 2.5 Flash
- 💾 Lieferanten-Memory (lernt welches Konto fuer welchen Lieferant)
- ✅ Human-in-the-Loop Freigabe via Telegram-Buttons
- 🏦 Direkte Bexio-Buchung
- 📊 `/stats` und `/vendors` fuer Uebersicht

## Tech-Stack

- **Python 3.11+**
- **python-telegram-bot v21** (async)
- **google-genai** (Gemini SDK, neu - NICHT das alte google-generativeai)
- **Supabase** (Postgres + Storage)
- **Bexio REST API v2 + v3**
- **Railway** (Deployment als Worker)

## Setup

### 1. Voraussetzungen

- Telegram Bot Token (via @BotFather)
- Bexio Personal Access Token
- Supabase Projekt (mit dem SQL-Schema deployed)
- Google AI Studio API Key (aistudio.google.com)
- GitHub Account + Railway Account

### 2. Environment Variables

Kopiere `.env.example` zu `.env` und fuelle alle Werte aus:

- `TELEGRAM_BOT_TOKEN` - von @BotFather
- `TELEGRAM_ALLOWED_CHAT_IDS` - deine Chat-ID (komma-separiert fuer mehrere)
- `BEXIO_API_TOKEN` - dein PAT
- `BEXIO_API_BASE_URL` - `https://api.bexio.com`
- `SUPABASE_URL` - aus Supabase Dashboard
- `SUPABASE_SERVICE_ROLE_KEY` - aus Supabase Dashboard (NICHT anon key)
- `SUPABASE_STORAGE_BUCKET` - `invoices`
- `GEMINI_API_KEY` - aus aistudio.google.com
- `GEMINI_MODEL` - `gemini-2.5-flash`
- `LOG_LEVEL` - `INFO`
- `ENVIRONMENT` - `development` oder `production`

### 3. Lokaler Test (optional)

\`\`\`bash
pip install -r requirements.txt
python -m app.main
\`\`\`

### 4. Railway Deploy

1. **GitHub Repo** pushen (inkl. aller Files in `app/`, requirements.txt, Procfile, railway.json)
2. Auf **railway.com** → New Project → Deploy from GitHub Repo
3. Repo auswaehlen
4. Unter **Variables** alle ENV-Werte aus Punkt 2 eintragen
5. Railway erkennt automatisch das `Procfile` und deployed als Worker
6. Unter **Deployments** die Logs pruefen → solltest sehen: "✅ Bot laeuft. Warte auf Nachrichten…"

### 5. Ersten Sync durchfuehren

Im Telegram:

1. `/start` - Begruessung
2. `/sync` - Bexio-Kontenplan + MwSt-Codes in Supabase cachen

Dann ist der Bot bereit. Schick eine Test-Rechnung als PDF.

## Struktur

\`\`\`
visioskin-accounting-agent/
├── requirements.txt
├── Procfile                  # worker: python -m app.main
├── railway.json
├── .env.example
├── .gitignore
├── README.md
└── app/
    ├── __init__.py
    ├── main.py               # Entry Point
    ├── config.py             # ENV Settings
    ├── utils.py              # Logger, normalize_vendor_name, format_chf
    ├── models.py             # Pydantic Schemas
    ├── db.py                 # Supabase DB Wrapper
    ├── storage.py            # Supabase Storage (File Upload)
    ├── bexio.py              # Bexio REST Client
    ├── gemini.py             # Gemini PDF-Extraktion
    └── bot.py                # Telegram Handlers
\`\`\`

## Wartung

### Bot-Logs auf Railway anschauen

Railway → Project → Deployments → aktuelle Deployment anklicken → Logs

### Neue Deploys

Einfach nach GitHub pushen → Railway deployed automatisch.

### Troubleshooting

- **Bot reagiert nicht**: Check Railway-Logs. Oft `TELEGRAM_BOT_TOKEN` falsch.
- **"Fuehre erst /sync aus"**: Kontenplan wurde noch nicht gecached. `/sync` ausfuehren.
- **Bexio 401**: API-Token abgelaufen oder falsch. Neu erstellen in Bexio.
- **Gemini-Fehler**: API-Key ungueltig oder Quota erreicht (Free Tier 500 Requests/Tag).

## Phasen-Roadmap

- ✅ **Phase 1**: Telegram-only, Kreditoren-Rechnungen, Lieferanten-Memory
- 🔜 **Phase 1.5**: Web-Dashboard mit History und Stats
- 🔜 **Phase 2**: IMAP-Polling fuer info@visioskin.ch
- 🔜 **Phase 3**: Debitoren-Rechnungen erstellen, Zahlungen (pain.001)
- 🔜 **Phase 4**: WhatsApp, Teams, OneDrive-Integration

## Lizenz

Privat / VisioSkin internal use.
