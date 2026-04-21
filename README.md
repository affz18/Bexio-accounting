# VisioSkin Accounting Agent

Ein Telegram-Bot, der eingehende Rechnungen via Google Gemini auswertet und in Bexio verbucht.

## Setup
1. Erstelle eine Python 3.11 Umgebung: `python -m venv venv`
2. Aktiviere sie: `source venv/bin/activate` (Mac/Linux) oder `venv\Scripts\activate` (Windows)
3. Installiere Abhängigkeiten: `pip install -r requirements.txt`
4. Kopiere `.env.example` zu `.env` und fülle die Variablen aus.
5. Starte den Bot: `python -m app.main` oder `fastapi run app/main.py --port 3000`

## Supabase Tabellen
Bitte stelle sicher, dass folgende Tabellen existieren:
- `vendors`
- `pending_invoices`
- `authorized_users`
- Storage Bucket: `invoices`

## Deployment auf Railway
- Projekt mit GitHub verbinden
- "Nixpacks" wird automatisch erkannt
- ENV-Variablen in Railway setzen
- Das `Procfile` startet den Bot als Worker. Alternativ als Web-Service mit Port (dann wird FastAPI health endpoint genutzt).
