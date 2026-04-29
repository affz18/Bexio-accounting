export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Einstellungen</h1>
        <p className="mt-1 text-foreground-muted">
          Konfiguration des aktuellen Mandanten.
        </p>
      </div>

      <div className="space-y-4">
        <SettingsSection
          title="Bexio-Anbindung"
          description="API-Token zum Lesen und Buchen in Bexio."
        >
          <div className="flex items-center gap-3">
            <input
              type="password"
              placeholder="bex_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
              className="input"
              defaultValue="••••••••••••••••"
              disabled
            />
            <button className="btn-secondary text-sm" disabled>Verbinden</button>
          </div>
          <p className="mt-2 text-xs text-foreground-muted">
            Aktuell kommt der Token aus der Env. Block 1C migriert das in die DB.
          </p>
        </SettingsSection>

        <SettingsSection
          title="Mail-Inbox"
          description="IMAP-Postfach das automatisch nach Belegen gescannt wird."
        >
          <div className="grid grid-cols-2 gap-3">
            <input className="input" placeholder="imap.mail.hostpoint.ch" disabled />
            <input className="input" placeholder="info@firma.ch" disabled />
            <input className="input col-span-2" placeholder="App-Passwort" type="password" disabled />
          </div>
          <p className="mt-2 text-xs text-foreground-muted">
            Aktuell aus Env - editierbar in Block 1D.
          </p>
        </SettingsSection>

        <SettingsSection
          title="Privat-Verrechnungskonto"
          description="Konto-Nr fuer 'privat bezahlt'-Belege."
        >
          <input className="input max-w-xs" defaultValue="2100" disabled />
        </SettingsSection>

        <SettingsSection
          title="Telegram-Benachrichtigungen"
          description="Wer kriegt automatische Notifications neuer Belege."
        >
          <input className="input max-w-md" placeholder="Chat-IDs (komma-separiert)" disabled />
        </SettingsSection>
      </div>
    </div>
  );
}

function SettingsSection({
  title, description, children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card p-6">
      <h2 className="font-semibold">{title}</h2>
      <p className="mt-1 text-sm text-foreground-muted">{description}</p>
      <div className="mt-4">{children}</div>
    </div>
  );
}
