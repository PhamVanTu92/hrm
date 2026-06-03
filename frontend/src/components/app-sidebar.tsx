"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  CalendarCheck,
  FileText,
  LayoutDashboard,
  LogOut,
  ScrollText,
  Settings,
  ShieldCheck,
  Users,
  Wallet,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { hasPermission } from "@/lib/rbac";
import { clearSessionHint } from "@/lib/session-cookie";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";

interface NavItem {
  href: string;
  label: string;
  icon: typeof Users;
  perm?: string;
}

const NAV: NavItem[] = [
  { href: "/", label: "Tổng quan", icon: LayoutDashboard },
  { href: "/employees", label: "Nhân viên", icon: Users, perm: "employee:read" },
  { href: "/attendance", label: "Chấm công", icon: CalendarCheck, perm: "attendance:read" },
  { href: "/approvals", label: "Duyệt đơn", icon: ScrollText, perm: "approval:act" },
  { href: "/payroll", label: "Bảng lương", icon: Wallet, perm: "payroll:read" },
  { href: "/payslips", label: "Phiếu lương", icon: FileText },
  { href: "/audit", label: "Kiểm toán", icon: ShieldCheck, perm: "audit:read" },
  {
    href: "/settings/dynamic-fields",
    label: "Trường động",
    icon: Settings,
    perm: "dynamic_field:manage",
  },
];

export function AppSidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const clear = useAuthStore((s) => s.clear);

  const logout = () => {
    clear();
    clearSessionHint();
    router.push("/login");
  };

  return (
    <aside className="flex h-screen w-60 flex-col border-r bg-card">
      <div className="px-6 py-5 text-lg font-bold">HRM</div>
      <nav className="flex-1 space-y-1 px-3">
        {NAV.filter((item) => !item.perm || hasPermission(user, item.perm)).map((item) => {
          const active = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t p-3">
        <div className="px-3 pb-2 text-xs text-muted-foreground">{user?.username}</div>
        <Button variant="ghost" size="sm" className="w-full justify-start" onClick={logout}>
          <LogOut className="h-4 w-4" />
          Đăng xuất
        </Button>
      </div>
    </aside>
  );
}
