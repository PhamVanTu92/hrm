import { api } from "@/lib/api-client";
import type { Envelope } from "@/types/api";
import type { ProfileFieldMeta } from "@/types/employee";

export interface ProfileCategory {
  id: number;
  code: string;
  name: string;
  sort_order: number;
}

export interface ProfileFieldCreate {
  category_id: number;
  field_key: string;
  label: string;
  data_type: ProfileFieldMeta["data_type"];
  options?: string[] | null;
  is_required?: boolean;
  is_encrypted?: boolean;
}

export interface DynamicProfile {
  employee_id: number;
  data: Record<string, unknown>;
}

export async function listProfileFields(): Promise<ProfileFieldMeta[]> {
  const { data } = await api.get<Envelope<ProfileFieldMeta[]>>("/employees/profile-fields");
  return data.data;
}

export async function createProfileField(payload: ProfileFieldCreate): Promise<ProfileFieldMeta> {
  const { data } = await api.post<Envelope<ProfileFieldMeta>>("/employees/profile-fields", payload);
  return data.data;
}

export async function listCategories(): Promise<ProfileCategory[]> {
  const { data } = await api.get<Envelope<ProfileCategory[]>>("/employees/profile-categories");
  return data.data;
}

export async function createCategory(payload: {
  code: string;
  name: string;
  sort_order?: number;
}): Promise<ProfileCategory> {
  const { data } = await api.post<Envelope<ProfileCategory>>(
    "/employees/profile-categories",
    payload,
  );
  return data.data;
}

export async function getProfile(employeeId: number): Promise<DynamicProfile> {
  const { data } = await api.get<Envelope<DynamicProfile>>(`/employees/${employeeId}/profile`);
  return data.data;
}

export async function saveProfile(
  employeeId: number,
  values: Record<string, unknown>,
): Promise<DynamicProfile> {
  const { data } = await api.put<Envelope<DynamicProfile>>(`/employees/${employeeId}/profile`, {
    data: values,
  });
  return data.data;
}
