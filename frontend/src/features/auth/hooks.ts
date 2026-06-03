"use client";

import { useMutation } from "@tanstack/react-query";

import { setSessionHint } from "@/lib/session-cookie";
import { useAuthStore } from "@/stores/auth-store";
import type { LoginRequest, Me } from "@/types/auth";

import { fetchMe, login } from "./api";

/** Log in, store tokens, then load the profile (perms) into the auth store. */
export function useLogin() {
  const setTokens = useAuthStore((s) => s.setTokens);
  const setUser = useAuthStore((s) => s.setUser);

  return useMutation<Me, Error, LoginRequest>({
    mutationFn: async (payload) => {
      const tokens = await login(payload);
      setTokens(tokens.access_token, tokens.refresh_token);
      const me = await fetchMe();
      setUser(me);
      setSessionHint(); // non-HttpOnly hint so middleware can route-guard
      return me;
    },
  });
}
