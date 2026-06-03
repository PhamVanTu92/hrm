export interface Employee {
  id: number;
  employee_code: string;
  full_name: string;
  department_id: number | null;
  position_id: number | null;
  manager_id: number | null;
  join_date: string | null;
  status: string;
}

export interface EmployeeCreate {
  employee_code: string;
  full_name: string;
  department_id?: number | null;
  position_id?: number | null;
  manager_id?: number | null;
  join_date?: string | null;
  national_id?: string | null;
  phone?: string | null;
  bank_account?: string | null;
  base_salary?: string | null;
}

export interface EmployeeFilter {
  department_id?: number;
  position_id?: number;
  status?: string;
  q?: string;
}

/** Metadata describing a dynamic profile field (settings/dynamic-fields). */
export interface ProfileFieldMeta {
  field_key: string;
  label: string;
  data_type: "TEXT" | "NUMBER" | "DATE" | "SELECT" | "BOOLEAN";
  options: string[] | null;
  is_required: boolean;
  is_encrypted: boolean;
}
