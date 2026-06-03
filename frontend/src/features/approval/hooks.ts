"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { approveInstance, myPending, rejectInstance, submitLeave } from "./api";

export function useMyPending() {
  return useQuery({ queryKey: ["approvals", "my-pending"], queryFn: myPending });
}

export function useApprove() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, comment }: { id: number; comment?: string }) =>
      approveInstance(id, comment),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["approvals"] }),
  });
}

export function useReject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, comment }: { id: number; comment?: string }) => rejectInstance(id, comment),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["approvals"] }),
  });
}

export function useSubmitLeave() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: submitLeave,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["approvals"] }),
  });
}
