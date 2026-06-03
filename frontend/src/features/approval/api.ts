import { api } from "@/lib/api-client";
import type { Envelope } from "@/types/api";
import type { ApprovalInstance, LeaveRequestCreate } from "@/types/approval";

export async function myPending(): Promise<ApprovalInstance[]> {
  const { data } = await api.get<Envelope<ApprovalInstance[]>>("/approvals/my-pending");
  return data.data;
}

export async function approveInstance(id: number, comment?: string): Promise<ApprovalInstance> {
  const { data } = await api.post<Envelope<ApprovalInstance>>(
    `/approvals/instances/${id}/approve`,
    { comment },
  );
  return data.data;
}

export async function rejectInstance(id: number, comment?: string): Promise<ApprovalInstance> {
  const { data } = await api.post<Envelope<ApprovalInstance>>(
    `/approvals/instances/${id}/reject`,
    { comment },
  );
  return data.data;
}

export async function submitLeave(payload: LeaveRequestCreate): Promise<ApprovalInstance> {
  const { data } = await api.post<Envelope<ApprovalInstance>>(
    "/approvals/leave-requests",
    payload,
  );
  return data.data;
}
