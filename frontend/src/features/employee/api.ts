import { api } from "@/lib/api-client";
import type { Envelope, Page, PageQuery } from "@/types/api";
import type { Employee, EmployeeCreate, EmployeeFilter } from "@/types/employee";

export async function listEmployees(
  params: PageQuery & EmployeeFilter,
): Promise<Page<Employee>> {
  // GET /employees returns a Page envelope ({ data, meta }) directly.
  const { data } = await api.get<Page<Employee>>("/employees", { params });
  return data;
}

export async function createEmployee(payload: EmployeeCreate): Promise<Employee> {
  const { data } = await api.post<Envelope<Employee>>("/employees", payload);
  return data.data;
}

export async function getEmployee(id: number): Promise<Employee> {
  const { data } = await api.get<Envelope<Employee>>(`/employees/${id}`);
  return data.data;
}
