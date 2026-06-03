"use client";

import { useQuery } from "@tanstack/react-query";

import type { AuditQuery } from "@/types/audit";

import { listAuditLogs } from "./api";

export function useAuditLogs(query: AuditQuery) {
  return useQuery({
    queryKey: ["audit", query],
    queryFn: () => listAuditLogs(query),
  });
}
