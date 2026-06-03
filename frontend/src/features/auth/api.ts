import { api } from "@/lib/api-client";
import type { Envelope } from "@/types/api";
import type { LoginRequest, Me, TokenResponse } from "@/types/auth";

/** POST /auth/login — returns a token pair (not enveloped). */
export async function login(payload: LoginRequest): Promise<TokenResponse> {
  const { data } = await api.post<TokenResponse>("/auth/login", payload);
  return data;
}

/** GET /auth/me — current user profile (enveloped). */
export async function fetchMe(): Promise<Me> {
  const { data } = await api.get<Envelope<Me>>("/auth/me");
  return data.data;
}

/** POST /auth/logout — revoke the refresh token. */
export async function logout(refreshToken: string): Promise<void> {
  await api.post("/auth/logout", { refresh_token: refreshToken });
}
