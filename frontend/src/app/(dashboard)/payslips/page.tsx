"use client";

import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api-client";
import type { Envelope } from "@/types/api";

interface Payslip {
  id: number;
  period: string;
  status: string;
  email_status: string;
  file_id: number | null;
}

async function fetchMyPayslips(): Promise<Payslip[]> {
  const { data } = await api.get<Envelope<Payslip[]>>("/payslips/me");
  return data.data;
}

export default function PayslipsPage() {
  const { data, isLoading } = useQuery({ queryKey: ["payslips", "me"], queryFn: fetchMyPayslips });

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Phiếu lương của tôi</h1>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Đang tải…</p>
      ) : !data?.length ? (
        <p className="text-sm text-muted-foreground">Chưa có phiếu lương.</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {data.map((p) => (
            <Card key={p.id}>
              <CardHeader>
                <CardTitle>Kỳ {p.period}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="text-sm text-muted-foreground">
                  Trạng thái: {p.status} · Email: {p.email_status}
                </div>
                <div className="flex gap-2">
                  {p.status === "PENDING" && (
                    <>
                      <Button
                        size="sm"
                        onClick={() => api.post(`/payslips/${p.id}/confirm`)}
                      >
                        Xác nhận
                      </Button>
                      <Button size="sm" variant="outline">
                        Phản hồi
                      </Button>
                    </>
                  )}
                  {p.file_id && (
                    <Button size="sm" variant="secondary" asChild>
                      <a href={`/api/v1/payslips/${p.id}/download`}>Tải PDF</a>
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
