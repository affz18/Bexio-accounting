"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();
  const redirect = params.get("redirect") || "/dashboard";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [signupMode, setSignupMode] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    const supabase = createClient();
    const { error } = signupMode
      ? await supabase.auth.signUp({ email, password })
      : await supabase.auth.signInWithPassword({ email, password });

    setLoading(false);
    if (error) {
      setError(error.message);
      return;
    }
    router.push(redirect);
    router.refresh();
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-6">
      <div className="w-full max-w-sm card p-8">
        <Link href="/" className="block text-sm text-foreground-muted hover:text-foreground">
          ← Zurueck
        </Link>
        <h1 className="mt-4 text-2xl font-semibold tracking-tight">
          {signupMode ? "Konto erstellen" : "Anmelden"}
        </h1>
        <p className="mt-1 text-sm text-foreground-muted">
          Bexio AI Workspace
        </p>

        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <div>
            <label className="text-sm font-medium">E-Mail</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input mt-1"
              placeholder="du@firma.ch"
              autoComplete="email"
            />
          </div>
          <div>
            <label className="text-sm font-medium">Passwort</label>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input mt-1"
              placeholder="Mindestens 8 Zeichen"
              autoComplete={signupMode ? "new-password" : "current-password"}
            />
          </div>
          {error && (
            <div className="text-sm text-danger">{error}</div>
          )}
          <button
            type="submit"
            disabled={loading}
            className="btn-primary w-full"
          >
            {loading ? "Moment…" : signupMode ? "Registrieren" : "Anmelden"}
          </button>
        </form>

        <button
          onClick={() => { setSignupMode((s) => !s); setError(null); }}
          className="mt-4 text-sm text-foreground-muted hover:text-foreground w-full text-center"
        >
          {signupMode
            ? "Schon ein Konto? Anmelden"
            : "Noch kein Konto? Registrieren"}
        </button>
      </div>
    </div>
  );
}
