"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { PageQuery } from "@/types/api";
import type { EmployeeFilter } from "@/types/employee";

import { createEmployee, getEmployee, listEmployees } from "./api";

export function useEmployees(params: PageQuery & EmployeeFilter) {
  return useQuery({
    queryKey: ["employees", params],
    queryFn: () => listEmployees(params),
  });
}

export function useEmployee(id: number) {
  return useQuery({
    queryKey: ["employee", id],
    queryFn: () => getEmployee(id),
    enabled: Number.isFinite(id),
  });
}

export function useCreateEmployee() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createEmployee,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["employees"] }),
  });
}
