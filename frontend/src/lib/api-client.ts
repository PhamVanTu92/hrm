import axios, {
  type AxiosError,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from "axios";

import { useAuthStore } from "@/stores/auth-store";
import type { ApiErrorBody } from "@/types/api";
import type { TokenResponse } from "@/types/auth";

/** Axios instance. baseURL is same-origin; Next rewrites /api/* to the backend. */
export const api = axios.create({
  baseURL: "/api/v1",
  withCredentials: true,
});

// --- attach the access token to every request ---
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = useAuthStore.getState().accessToken;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// --- refresh-token rotation on 401 (deduped across concurrent requests) ---
type RetriableConfig = AxiosRequestConfig & { _retry?: boolean };
let refreshing: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  const { refreshToken, setTokens, clear } = useAuthStore.getState();
  if (!refreshToken) {
    clear();
    throw new Error("No refresh token");
  }
  try {
    // Bare axios (no interceptors) to avoid a refresh loop.
    const { data } = await axios.post<TokenResponse>(
      "/api/v1/auth/refresh",
      { refresh_token: refreshToken },
      { withCredentials: true },
    );
    setTokens(data.access_token, data.refresh_token);
    return data.access_token;
  } catch (err) {
    clear();
    throw err;
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorBody>) => {
    const config = error.config as RetriableConfig | undefined;
    if (error.response?.status === 401 && config && !config._retry) {
      config._retry = true;
      try {
        refreshing ??= refreshAccessToken();
        const newToken = await refreshing;
        config.headers = config.headers ?? {};
        (config.headers as Record<string, string>).Authorization = `Bearer ${newToken}`;
        return api(config);
      } catch (refreshErr) {
        if (typeof window !== "undefined") {
          window.location.href = "/login";
        }
        return Promise.reject(refreshErr);
      } finally {
        refreshing = null;
      }
    }
    return Promise.reject(error);
  },
);

/** Extract a human-friendly message from an API error. */
export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const body = error.response?.data as ApiErrorBody | undefined;
    return body?.error?.message ?? error.message;
  }
  return error instanceof Error ? error.message : "Đã xảy ra lỗi";
}
