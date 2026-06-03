/**
 * Non-HttpOnly "session hint" cookie. It is NOT a security boundary — it only
 * lets the Next.js middleware route-guard on the server side. Real auth is the
 * in-memory access token + the backend's enforcement. In production, replace
 * this with the backend setting an HttpOnly refresh cookie and have middleware
 * check that instead.
 */
export const SESSION_HINT_COOKIE = "hrm_session";

export function setSessionHint(): void {
  if (typeof document === "undefined") return;
  // 7 days, matches refresh-token lifetime.
  document.cookie = `${SESSION_HINT_COOKIE}=1; path=/; max-age=${7 * 24 * 3600}; samesite=lax`;
}

export function clearSessionHint(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${SESSION_HINT_COOKIE}=; path=/; max-age=0; samesite=lax`;
}
