import Link from "next/link";
import { ArrowRight, Mail, Brain, Building2 } from "lucide-react";

export default function LandingPage() {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Top-Nav */}
      <header className="border-b border-border">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="font-semibold tracking-tight">Bexio AI Workspace</div>
          <Link href="/login" className="btn-secondary text-sm">
            Anmelden
          </Link>
        </div>
      </header>

      {/* Hero */}
      <section className="flex-1 max-w-4xl mx-auto px-6 py-20 text-center">
        <h1 className="text-5xl md:text-6xl font-bold tracking-tight">
          Lieferanten-Rechnungen erscheinen,<br />
          <span className="text-accent">der Bot bucht.</span>
        </h1>
        <p className="mt-6 text-lg text-foreground-muted max-w-2xl mx-auto">
          Wir ziehen Belege automatisch aus deiner Mailbox, lesen sie aus und
          buchen sie in Bexio - inkl. Bank-Abgleich. Du bestaetigst per
          Telegram, Teams oder im Web. Ein Tool, mehrere Mandate.
        </p>
        <div className="mt-10 flex items-center justify-center gap-3">
          <Link href="/login" className="btn-primary text-base">
            Anmelden <ArrowRight className="w-4 h-4" />
          </Link>
          <a href="#features" className="btn-ghost text-base">
            So funktioniert&apos;s
          </a>
        </div>
      </section>

      {/* Drei-Punkte */}
      <section id="features" className="border-t border-border py-20">
        <div className="max-w-6xl mx-auto px-6 grid md:grid-cols-3 gap-8">
          <Feature
            icon={<Mail className="w-6 h-6" />}
            title="Mail-Inbox automatisch"
            text="Belege landen automatisch in der Pipeline - sobald sie in der Mailbox erscheinen. Kein Foto, kein Upload."
          />
          <Feature
            icon={<Brain className="w-6 h-6" />}
            title="Lernt aus eurer Buchhaltung"
            text="Aus 12 Monaten Bexio-History bauen wir das Vendor-Memory. Beim 25. Swisscom-Beleg trifft der Konto-Vorschlag."
          />
          <Feature
            icon={<Building2 className="w-6 h-6" />}
            title="Mehrere Mandate, ein Dashboard"
            text="Ob KMU mit einem Mandat oder Treuhand mit 30 - alles in einer Ansicht. Pro Mandat Bexio, IMAP, Konto-Mapping."
          />
        </div>
      </section>

      <footer className="border-t border-border py-8 text-center text-sm text-foreground-muted">
        Schweizer SaaS, nDSG-konform.
      </footer>
    </div>
  );
}

function Feature({
  icon, title, text,
}: { icon: React.ReactNode; title: string; text: string }) {
  return (
    <div>
      <div className="w-12 h-12 rounded-lg bg-primary/5 text-primary flex items-center justify-center">
        {icon}
      </div>
      <h3 className="mt-4 font-semibold text-lg">{title}</h3>
      <p className="mt-2 text-foreground-muted">{text}</p>
    </div>
  );
}
