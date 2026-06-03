export interface AuditLog {
  id: number;
  created_at: string;
  actor_id: number | null;
  action: string;
  entity: string;
  entity_id: string | null;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  ip: string | null;
  user_agent: string | null;
}

export interface AuditQuery {
  entity?: string;
  entity_id?: string;
  actor_id?: number;
  action?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  size?: number;
}
