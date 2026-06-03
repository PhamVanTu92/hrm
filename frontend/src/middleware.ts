import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_HINT_COOKIE } from "@/lib/session-cookie";

const PUBLIC_PATHS = ["/login", "/sso"];

/**
 * Route guard (defense-in-depth — the backend is the real enforcer).
 * Checks the non-HttpOnly session-hint cookie: unauthenticated users are sent
 * to /login, and authenticated users are bounced away from /login. Swap the
 * cookie check for the backend's HttpOnly refresh cookie in production.
 */
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const authed = req.cookies.has(SESSION_HINT_COOKIE);
  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p));

  if (!authed && !isPublic) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }
  if (authed && isPublic) {
    const url = req.nextUrl.clone();
    url.pathname = "/";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // Skip Next internals, the API proxy, and static assets.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api).*)"],
};
