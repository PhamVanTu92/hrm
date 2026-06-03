import { z } from "zod";

import type { ProfileFieldMeta } from "@/types/employee";

/**
 * Build a Zod schema from dynamic field metadata. Mirrors the backend's
 * server-side validation (app/modules/employee/service._validate_profile) so
 * the client rejects bad input before it hits the API.
 */
export function buildZodSchema(fields: ProfileFieldMeta[]): z.ZodObject<z.ZodRawShape> {
  const shape: z.ZodRawShape = {};

  for (const field of fields) {
    let schema: z.ZodTypeAny;
    switch (field.data_type) {
      case "NUMBER":
        schema = z.coerce.number({ invalid_type_error: "Phải là số" });
        break;
      case "BOOLEAN":
        schema = z.boolean();
        break;
      case "DATE":
        schema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Ngày không hợp lệ (YYYY-MM-DD)");
        break;
      case "SELECT":
        schema =
          field.options && field.options.length
            ? z.enum([field.options[0], ...field.options.slice(1)])
            : z.string();
        break;
      default:
        schema = z.string();
    }

    if (!field.is_required) {
      schema = schema.optional().or(z.literal(""));
    } else if (field.data_type === "TEXT" || field.data_type === "SELECT") {
      schema = (schema as z.ZodString).min(1, "Bắt buộc nhập");
    }

    shape[field.field_key] = schema;
  }

  return z.object(shape);
}
