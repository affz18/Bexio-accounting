export default function ReconciliationPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Bank-Abgleich</h1>
        <p className="mt-1 text-foreground-muted">
          camt.054-Datei hochladen und Zahlungen automatisch matchen.
        </p>
      </div>

      <div className="card p-12 border-dashed text-center">
        <div className="mx-auto w-12 h-12 rounded-full bg-primary/5 text-primary flex items-center justify-center">
          <span className="text-2xl">⬆</span>
        </div>
        <h3 className="mt-4 font-medium">camt-Datei hier ablegen</h3>
        <p className="mt-1 text-sm text-foreground-muted">
          Aus dem Online-Banking exportiert (camt.054 oder camt.053)
        </p>
        <button className="mt-4 btn-primary text-sm" disabled>
          Datei waehlen
        </button>
        <p className="mt-3 text-xs text-foreground-muted">
          Heute via Telegram funktional - Web-Upload kommt in Block 1E.
        </p>
      </div>
    </div>
  );
}
