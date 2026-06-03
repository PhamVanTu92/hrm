export interface StepInstance {
  id: number;
  step_order: number;
  approver_user_id: number;
  due_at: string | null;
  action: string | null;
  comment: string | null;
  acted_at: string | null;
  escalated: boolean;
}

export interface ApprovalInstance {
  id: number;
  workflow_id: number;
  target_type: string;
  target_id: number;
  requester_id: number;
  employee_id: number;
  current_step: number;
  status: string;
  completed_at: string | null;
  steps: StepInstance[];
}

export interface LeaveRequestCreate {
  employee_id: number;
  leave_type: string;
  start_date: string;
  end_date: string;
  is_paid: boolean;
  reason?: string;
}
