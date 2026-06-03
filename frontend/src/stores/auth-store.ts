import { create } from "zustand";

import type { Me } from "@/types/auth";

interface AuthState {
  /** Access token — kept in memory only (never localStorage) to limit XSS blast radius. */
  accessToken: string | null;
  /**
   * Refresh token. In production this should live in an HttpOnly Secure cookie
   * set by the backend; the current API returns it in the JSON body, so the
   * scaffold holds it in memory. Moving it to a cookie is a hardening step.
   */
  refreshToken: string | null;
  user: Me | null;
  setTokens: (access: string, refresh: string) => void;
  setUser: (user: Me) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  refreshToken: null,
  user: null,
  setTokens: (accessToken, refreshToken) => set({ accessToken, refreshToken }),
  setUser: (user) => set({ user }),
  clear: () => set({ accessToken: null, refreshToken: null, user: null }),
}));
