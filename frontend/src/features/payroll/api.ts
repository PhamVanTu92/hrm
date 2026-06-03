import { api } from "@/lib/api-client";
import type { Envelope } from "@/types/api";
import type { ComponentCreate, ImportReport, PayrollRun, SalaryComponent } from "@/types/payroll";

export async function listComponents(): Promise<SalaryComponent[]> {
  const { data } = await api.get<Envelope<SalaryComponent[]>>("/payroll/components");
  return data.data;
}

export async function createComponent(payload: ComponentCreate): Promise<SalaryComponent> {
  const { data } = await api.post<Envelope<SalaryComponent>>("/payroll/components", payload);
  return data.data;
}

export async function createPeriod(code: string): Promise<{ id: number; code: string }> {
  const { data } = await api.post<Envelope<{ id: number; code: string }>>("/payroll/periods", {
    code,
  });
  return data.data;
}

export async function createRun(periodCode: string): Promise<PayrollRun> {
  const { data } = await api.post<Envelope<PayrollRun>>("/payroll/runs", {
    period_code: periodCode,
  });
  return data.data;
}

export async function calculateRun(runId: number): Promise<{ calculated: number }> {
  const { data } = await api.post<Envelope<{ calculated: number }>>(
    `/payroll/runs/${runId}/calculate`,
    {},
  );
  return data.data;
}

export async function lockRun(runId: number): Promise<PayrollRun> {
  const { data } = await api.post<Envelope<PayrollRun>>(`/payroll/runs/${runId}/lock`);
  return data.data;
}

/** Upload an .xlsx of INPUT values; returns the ok/errors report. */
export async function importInput(period: string, file: File): Promise<ImportReport> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<Envelope<ImportReport>>("/payroll/input/import", form, {
    params: { period },
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data.data;
}

/** Same-origin link to download the Excel input template for a period. */
export function templateUrl(period: string): string {
  return `/api/v1/payroll/input/template?period=${encodeURIComponent(period)}`;
}
