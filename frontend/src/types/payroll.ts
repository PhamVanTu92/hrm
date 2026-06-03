export interface SalaryComponent {
  id: number;
  code: string;
  var_code: string;
  name: string;
  value_type: "INPUT" | "FIXED" | "FORMULA";
  default_value: string | null;
  expression: string | null;
  is_active: boolean;
}

export interface ComponentCreate {
  code: string;
  name: string;
  value_type: "INPUT" | "FIXED" | "FORMULA";
  var_code?: string;
  default_value?: string;
  expression?: string;
}

export interface PayrollRun {
  id: number;
  period_id: number;
  status: string;
  locked_at: string | null;
  note: string | null;
}

export interface ImportReport {
  ok: number;
  errors: { row: number; error: string }[];
}
