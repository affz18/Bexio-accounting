import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

/**
 * Auth-Middleware: refresht das Supabase-JWT bei jedem Request und
 * leitet nicht-authentifizierte Requests auf /login um.
 *
 * Public-Routes (/login, /, /api/public/*) sind ausgenommen.
 *
 * Defensiv: wenn ENV nicht konfiguriert ist (Build ohne Supabase-Vars
 * oder Misconfiguration), faellt die Middleware zurueck auf "kein Auth-
 * Check" und schreibt einen Warning-Log. Damit kriegt man eine sinnvolle
 * Seite statt MIDDLEWARE_INVOCATION_FAILED.
 */
export async function middleware(request: NextRequest) {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  // ENV nicht da -> einfach durchlassen, der Page-Code zeigt dann die
  // Konfigurations-Hinweise. Crash hier waere fuer User unverstaendlich.
  if (!supabaseUrl || !supabaseKey) {
    console.error(
      "[middleware] NEXT_PUBLIC_SUPABASE_URL/ANON_KEY nicht gesetzt - skipping auth check",
    );
    return NextResponse.next({ request: { headers: request.headers } });
  }

  let response = NextResponse.next({ request: { headers: request.headers } });

  try {
    const supabase = createServerClient(supabaseUrl, supabaseKey, {
      cookies: {
        get(name: string) {
          return request.cookies.get(name)?.value;
        },
        set(name: string, value: string, options: CookieOptions) {
          request.cookies.set({ name, value, ...options });
          response = NextResponse.next({ request: { headers: request.headers } });
          response.cookies.set({ name, value, ...options });
        },
        remove(name: string, options: CookieOptions) {
          request.cookies.set({ name, value: "", ...options });
          response = NextResponse.next({ request: { headers: request.headers } });
          response.cookies.set({ name, value: "", ...options });
        },
      },
    });

    // Refreshed das Token bei jedem Request
    const {
      data: { user },
    } = await supabase.auth.getUser();

    const isAuthRoute =
      request.nextUrl.pathname.startsWith("/login") ||
      request.nextUrl.pathname.startsWith("/auth");
    const isPublicRoute =
      isAuthRoute ||
      request.nextUrl.pathname === "/" ||
      request.nextUrl.pathname.startsWith("/_next") ||
      request.nextUrl.pathname.startsWith("/api/public");

    if (!user && !isPublicRoute) {
      const url = request.nextUrl.clone();
      url.pathname = "/login";
      url.searchParams.set("redirect", request.nextUrl.pathname);
      return NextResponse.redirect(url);
    }

    if (user && isAuthRoute) {
      const url = request.nextUrl.clone();
      url.pathname = "/dashboard";
      url.searchParams.delete("redirect");
      return NextResponse.redirect(url);
    }

    return response;
  } catch (e) {
    // Defensive: bei Supabase-Fehlern in der Middleware nicht 500en
    console.error("[middleware] Auth-Check fehlgeschlagen:", e);
    return NextResponse.next({ request: { headers: request.headers } });
  }
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
