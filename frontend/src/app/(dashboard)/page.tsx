"use client";

import { useMemo } from "react";

import { Can } from "@/components/can";
import { BarChartCard } from "@/components/charts/bar-chart-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuditLogs } from "@/features/audit/hooks";
import { useAuthStore } from "@/stores/auth-store";

function countBy<T>(items: T[], key: (item: T) => string): { label: string; value: number }[] {
  const map = new Map<string, number>();
  for (const item of items) {
    const k = key(item);
    map.set(k, (map.get(k) ?? 0) + 1);
  }
  return [...map.entries()].map(([label, value]) => ({ label, value }));
}

/** Mounted only for users with audit:read (so the query never 403s). */
function AuditActivity() {
  const { data } = useAuditLogs({ size: 100, page: 1 });
  const byAction = useMemo(() => countBy(data?.data ?? [], (l) => l.action), [data]);
  const byEntity = useMemo(() => countBy(data?.data ?? [], (l) => l.entity), [data]);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <BarChartCard title="Hoạt động theo loại (100 bản ghi gần nhất)" data={byAction} />
      <BarChartCard title="Hoạt động theo đối tượng" data={byEntity} />
    </div>
  );
}

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Xin chào, {user?.username}</h1>
        <p className="text-muted-foreground">Vai trò: {user?.roles.join(", ") || "—"}</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { title: "Chấm công tháng", value: "—" },
          { title: "Đơn chờ duyệt", value: "—" },
          { title: "Kỳ lương", value: "—" },
          { title: "Phiếu lương", value: "—" },
        ].map((c) => (
          <Card key={c.title}>
            <CardHeader>
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {c.title}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{c.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Can
        perm="audit:read"
        fallback={
          <p className="text-sm text-muted-foreground">
            Biểu đồ tổng hợp dành cho quản trị (cần quyền audit:read). Các thẻ trên sẽ nối API tổng
            hợp server-side.
          </p>
        }
      >
        <AuditActivity />
      </Can>
    </div>
  );
}
