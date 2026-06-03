import type { Me } from "@/types/auth";

/** True if the user holds every listed permission. */
export function hasPermission(user: Me | null, ...needed: string[]): boolean {
  if (!user) return false;
  const owned = new Set(user.permissions);
  return needed.every((p) => owned.has(p));
}

/** Permission catalog mirror (keep in sync with backend app/core/rbac.py). */
export const PERMISSIONS = {
  EMPLOYEE_READ: "employee:read",
  EMPLOYEE_WRITE: "employee:write",
  SALARY_VIEW: "salary:view_sensitive",
  ATTENDANCE_READ: "attendance:read",
  ATTENDANCE_MANAGE: "attendance:manage",
  APPROVAL_ACT: "approval:act",
  APPROVAL_MANAGE: "approval:manage",
  PAYROLL_READ: "payroll:read",
  PAYROLL_RUN: "payroll:run",
  PAYROLL_LOCK: "payroll:lock",
  AUDIT_READ: "audit:read",
} as const;
