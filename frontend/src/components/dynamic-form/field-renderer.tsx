"use client";

import { Lock } from "lucide-react";
import type { UseFormReturn } from "react-hook-form";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ProfileFieldMeta } from "@/types/employee";

interface FieldRendererProps {
  field: ProfileFieldMeta;
  form: UseFormReturn<Record<string, unknown>>;
  canViewEncrypted?: boolean;
}

/** Render one dynamic field according to its data_type. */
export function FieldRenderer({ field, form, canViewEncrypted = false }: FieldRendererProps) {
  const { register, formState } = form;
  const error = formState.errors[field.field_key]?.message as string | undefined;
  const masked = field.is_encrypted && !canViewEncrypted;

  return (
    <div className="space-y-1.5">
      <Label htmlFor={field.field_key} className="flex items-center gap-1">
        {field.label}
        {field.is_required && <span className="text-destructive">*</span>}
        {field.is_encrypted && <Lock className="h-3 w-3 text-muted-foreground" />}
      </Label>

      {field.data_type === "BOOLEAN" ? (
        <input id={field.field_key} type="checkbox" {...register(field.field_key)} />
      ) : field.data_type === "SELECT" ? (
        <select
          id={field.field_key}
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          disabled={masked}
          {...register(field.field_key)}
        >
          <option value="">— Chọn —</option>
          {(field.options ?? []).map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      ) : (
        <Input
          id={field.field_key}
          type={
            field.data_type === "NUMBER" ? "number" : field.data_type === "DATE" ? "date" : "text"
          }
          placeholder={masked ? "••• (chỉ HR xem được)" : undefined}
          disabled={masked}
          {...register(field.field_key)}
        />
      )}

      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
