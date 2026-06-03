"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  calculateRun,
  createComponent,
  createPeriod,
  createRun,
  importInput,
  listComponents,
  lockRun,
} from "./api";

export function useComponents() {
  return useQuery({ queryKey: ["payroll", "components"], queryFn: listComponents });
}

export function useCreateComponent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createComponent,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["payroll", "components"] }),
  });
}

export function useCreatePeriod() {
  return useMutation({ mutationFn: createPeriod });
}

export function useCreateRun() {
  return useMutation({ mutationFn: createRun });
}

export function useCalculateRun() {
  return useMutation({ mutationFn: calculateRun });
}

export function useLockRun() {
  return useMutation({ mutationFn: lockRun });
}

export function useImportInput() {
  return useMutation({
    mutationFn: ({ period, file }: { period: string; file: File }) => importInput(period, file),
  });
}
