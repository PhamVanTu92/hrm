"use client";

import type { ReactNode } from "react";

import { hasPermission } from "@/lib/rbac";
import { useAuthStore } from "@/stores/auth-store";

interface CanProps {
  perm: string | string[];
  children: ReactNode;
  fallback?: ReactNode;
}

/**
 * Render children only if the current user holds the permission(s).
 * UI gating only — the backend remains the real authorization enforcer.
 */
export function Can({ perm, children, fallback = null }: CanProps) {
  const user = useAuthStore((s) => s.user);
  const needed = Array.isArray(perm) ? perm : [perm];
  return hasPermission(user, ...needed) ? <>{children}</> : <>{fallback}</>;
}
