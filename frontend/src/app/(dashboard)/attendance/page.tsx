"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function AttendancePage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Chấm công</h1>
      <Card>
        <CardHeader>
          <CardTitle>Bảng công theo kỳ</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Gọi <code>GET /attendance/daily</code> và <code>/attendance/monthly/&#123;emp&#125;/&#123;period&#125;</code>;
          dùng <code>DataTable</code> server-side. HR điều chỉnh công qua{" "}
          <code>PATCH /attendance/daily/&#123;id&#125;</code> (quyền <code>attendance:manage</code>).
        </CardContent>
      </Card>
    </div>
  );
}
