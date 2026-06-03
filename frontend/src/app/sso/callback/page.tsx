"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { fetchMe } from "@/features/auth/api";
import { setSessionHint } from "@/lib/session-cookie";
import { useAuthStore } from "@/stores/auth-store";

/**
 * Landing page for the Microsoft SSO redirect. The backend redirects here with
 * the issued tokens in the URL fragment (#access_token=...&refresh_token=...);
 * we store them, load the profile, then go to the dashboard.
 */
export default function SsoCallbackPage() {
  const router = useRouter();
  const setTokens = useAuthStore((s) => s.setTokens);
  const setUser = useAuthStore((s) => s.setUser);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const access = params.get("access_token");
    const refresh = params.get("refresh_token");
    if (!access || !refresh) {
      setError("Thiếu token từ SSO. Vui lòng đăng nhập lại.");
      return;
    }
    // Clear the fragment so tokens don't linger in the URL/history.
    window.history.replaceState(null, "", window.location.pathname);
    setTokens(access, refresh);
    fetchMe()
      .then((me) => {
        setUser(me);
        setSessionHint();
        router.replace("/");
      })
      .catch(() => setError("Không tải được hồ sơ người dùng."));
  }, [router, setTokens, setUser]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      {error ? (
        <div className="space-y-3 text-center">
          <p className="text-destructive">{error}</p>
          <a href="/login" className="text-primary underline">
            Về trang đăng nhập
          </a>
        </div>
      ) : (
        <p className="text-muted-foreground">Đang hoàn tất đăng nhập Microsoft…</p>
      )}
    </div>
  );
}
