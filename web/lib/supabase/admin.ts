import { createClient } from "@supabase/supabase-js";

/**
 * Server-side Admin-Client mit SERVICE_ROLE-Key.
 *
 * **NUR auf dem Server verwenden** - der Service-Role-Key umgeht RLS und
 * darf nie im Browser landen. Wir nutzen ihn fuer Read-Queries solange RLS
 * noch nicht aktiviert ist (Block 1A der Web-UI = Demo-Modus, single-tenant).
 *
 * Block 1C aktiviert RLS und macht Reads ueber den Anon-Client. Dieser
 * Admin-Client bleibt dann fuer privilegierte Operationen (z.B. Onboarding,
 * Tenant-Setup, Bot-Integration).
 */
export function createAdminClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!url || !key) {
    throw new Error(
      "Supabase nicht konfiguriert: NEXT_PUBLIC_SUPABASE_URL und " +
      "SUPABASE_SERVICE_ROLE_KEY in .env.local setzen.",
    );
  }

  return createClient(url, key, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
    },
  });
}
