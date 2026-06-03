"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createCategory,
  createProfileField,
  getProfile,
  listCategories,
  listProfileFields,
  saveProfile,
} from "./api";

export function useProfileFields() {
  return useQuery({ queryKey: ["profile-fields"], queryFn: listProfileFields });
}

export function useCategories() {
  return useQuery({ queryKey: ["profile-categories"], queryFn: listCategories });
}

export function useCreateField() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createProfileField,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile-fields"] }),
  });
}

export function useCreateCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createCategory,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile-categories"] }),
  });
}

export function useProfile(employeeId: number) {
  return useQuery({
    queryKey: ["profile", employeeId],
    queryFn: () => getProfile(employeeId),
    enabled: Number.isFinite(employeeId),
  });
}

export function useSaveProfile(employeeId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, unknown>) => saveProfile(employeeId, values),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile", employeeId] }),
  });
}
