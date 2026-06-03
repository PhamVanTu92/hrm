"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { type Resolver, useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import type { ProfileFieldMeta } from "@/types/employee";

import { buildZodSchema } from "./build-zod-schema";
import { FieldRenderer } from "./field-renderer";

type FormValues = Record<string, unknown>;

interface DynamicFormProps {
  fields: ProfileFieldMeta[];
  defaultValues?: FormValues;
  canViewEncrypted?: boolean;
  onSubmit: (values: FormValues) => void | Promise<void>;
  submitLabel?: string;
}

/**
 * Render a form purely from field metadata (`/employees/{id}/profile` +
 * dynamic-field definitions). Validation is generated from the same metadata
 * via Zod, mirroring the backend's dynamic validation.
 */
export function DynamicForm({
  fields,
  defaultValues = {},
  canViewEncrypted = false,
  onSubmit,
  submitLabel = "Lưu",
}: DynamicFormProps) {
  const schema = buildZodSchema(fields);
  const form = useForm<FormValues>({
    resolver: zodResolver(schema) as unknown as Resolver<FormValues>,
    defaultValues,
  });

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
      {fields.map((field) => (
        <FieldRenderer
          key={field.field_key}
          field={field}
          form={form}
          canViewEncrypted={canViewEncrypted}
        />
      ))}
      <Button type="submit" disabled={form.formState.isSubmitting}>
        {submitLabel}
      </Button>
    </form>
  );
}
