import { api } from "@/lib/api-client";
import type { Page } from "@/types/api";
import type { AuditLog, AuditQuery } from "@/types/audit";

export async function listAuditLogs(query: AuditQuery): Promise<Page<AuditLog>> {
  // Drop empty params so the backend doesn't filter on blanks.
  const params = Object.fromEntries(
    Object.entries(query).filter(([, v]) => v !== undefined && v !== ""),
  );
  const { data } = await api.get<Page<AuditLog>>("/audit/logs", { params });
  return data;
}
