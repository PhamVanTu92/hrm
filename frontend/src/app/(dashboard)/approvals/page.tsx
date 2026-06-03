"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Can } from "@/components/can";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApprove, useMyPending, useReject, useSubmitLeave } from "@/features/approval/hooks";
import { apiErrorMessage } from "@/lib/api-client";

function LeaveForm() {
  const submit = useSubmitLeave();
  const [employeeId, setEmployeeId] = useState("");
  const [leaveType, setLeaveType] = useState("ANNUAL");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [isPaid, setIsPaid] = useState(true);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    submit.mutate(
      {
        employee_id: Number(employeeId),
        leave_type: leaveType,
        start_date: start,
        end_date: end,
        is_paid: isPaid,
      },
      {
        onSuccess: () => toast.success("Đã gửi đơn nghỉ phép"),
        onError: (err) => toast.error(apiErrorMessage(err)),
      },
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Nộp đơn nghỉ phép</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="emp">Mã NV (id)</Label>
            <Input
              id="emp"
              value={employeeId}
              onChange={(e) => setEmployeeId(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="lt">Loại phép</Label>
            <Input id="lt" value={leaveType} onChange={(e) => setLeaveType(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sd">Từ ngày</Label>
            <Input id="sd" type="date" value={start} onChange={(e) => setStart(e.target.value)} required />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ed">Đến ngày</Label>
            <Input id="ed" type="date" value={end} onChange={(e) => setEnd(e.target.value)} required />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={isPaid} onChange={(e) => setIsPaid(e.target.checked)} />
            Nghỉ có lương
          </label>
          <div className="sm:col-span-2">
            <Button type="submit" disabled={submit.isPending}>
              Gửi đơn
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function PendingInbox() {
  const pending = useMyPending();
  const approve = useApprove();
  const reject = useReject();
  const [comments, setComments] = useState<Record<number, string>>({});

  if (pending.isLoading) return <p className="text-muted-foreground">Đang tải…</p>;
  if (!pending.data?.length)
    return <p className="text-sm text-muted-foreground">Không có đơn chờ bạn duyệt.</p>;

  return (
    <div className="space-y-3">
      {pending.data.map((inst) => (
        <Card key={inst.id}>
          <CardContent className="flex flex-wrap items-center gap-3 pt-6">
            <div className="flex-1">
              <div className="font-medium">
                Đơn #{inst.id} · {inst.target_type} · bước {inst.current_step}
              </div>
              <div className="text-sm text-muted-foreground">
                NV #{inst.employee_id} · trạng thái {inst.status}
              </div>
            </div>
            <Input
              placeholder="Ghi chú…"
              className="w-48"
              value={comments[inst.id] ?? ""}
              onChange={(e) => setComments((c) => ({ ...c, [inst.id]: e.target.value }))}
            />
            <Button
              size="sm"
              onClick={() =>
                approve.mutate(
                  { id: inst.id, comment: comments[inst.id] },
                  {
                    onSuccess: () => toast.success("Đã duyệt"),
                    onError: (err) => toast.error(apiErrorMessage(err)),
                  },
                )
              }
            >
              Duyệt
            </Button>
            <Button
              size="sm"
              variant="destructive"
              onClick={() =>
                reject.mutate(
                  { id: inst.id, comment: comments[inst.id] },
                  {
                    onSuccess: () => toast.success("Đã từ chối"),
                    onError: (err) => toast.error(apiErrorMessage(err)),
                  },
                )
              }
            >
              Từ chối
            </Button>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export default function ApprovalsPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Duyệt đơn</h1>
      <Can
        perm="approval:act"
        fallback={<p className="text-sm text-muted-foreground">Bạn không có quyền duyệt.</p>}
      >
        <PendingInbox />
      </Can>
      <LeaveForm />
    </div>
  );
}
