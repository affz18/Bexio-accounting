"use client";

import { createBrowserClient } from "@supabase/ssr";

/**
 * Supabase-Client fuer Browser/Client-Components.
 * Nutzt anon-key + RLS - der Client kann nur Daten sehen die der eingeloggte
 * User auch sehen darf (gemaess RLS-Policies).
 */
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
