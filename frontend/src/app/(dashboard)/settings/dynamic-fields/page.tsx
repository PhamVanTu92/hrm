"use client";

import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Lock } from "lucide-react";
import { toast } from "sonner";

import { DataTable } from "@/components/data-table/data-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useCategories,
  useCreateCategory,
  useCreateField,
  useProfileFields,
} from "@/features/dynamic-field/hooks";
import { apiErrorMessage } from "@/lib/api-client";
import { hasPermission } from "@/lib/rbac";
import { useAuthStore } from "@/stores/auth-store";
import type { ProfileFieldMeta } from "@/types/employee";

const DATA_TYPES: ProfileFieldMeta["data_type"][] = [
  "TEXT",
  "NUMBER",
  "DATE",
  "SELECT",
  "BOOLEAN",
];

const fieldColumns: ColumnDef<ProfileFieldMeta>[] = [
  { accessorKey: "field_key", header: "Khóa" },
  { accessorKey: "label", header: "Nhãn" },
  { accessorKey: "data_type", header: "Kiểu" },
  {
    accessorKey: "is_required",
    header: "Bắt buộc",
    cell: ({ row }) => (row.original.is_required ? "✓" : "—"),
  },
  {
    accessorKey: "is_encrypted",
    header: "Mã hóa",
    cell: ({ row }) => (row.original.is_encrypted ? <Lock className="h-4 w-4" /> : "—"),
  },
];

export default function DynamicFieldsPage() {
  const user = useAuthStore((s) => s.user);
  const canManage = hasPermission(user, "dynamic_field:manage");

  const fields = useProfileFields();
  const categories = useCategories();
  const createCategory = useCreateCategory();
  const createField = useCreateField();

  const [catCode, setCatCode] = useState("");
  const [catName, setCatName] = useState("");

  const [fieldKey, setFieldKey] = useState("");
  const [label, setLabel] = useState("");
  const [dataType, setDataType] = useState<ProfileFieldMeta["data_type"]>("TEXT");
  const [categoryId, setCategoryId] = useState<number | "">("");
  const [optionsCsv, setOptionsCsv] = useState("");
  const [isRequired, setIsRequired] = useState(false);
  const [isEncrypted, setIsEncrypted] = useState(false);

  if (!canManage) {
    return <p className="text-muted-foreground">Bạn không có quyền quản lý trường động.</p>;
  }

  const submitCategory = (e: React.FormEvent) => {
    e.preventDefault();
    createCategory.mutate(
      { code: catCode, name: catName },
      {
        onSuccess: () => {
          toast.success("Đã tạo nhóm");
          setCatCode("");
          setCatName("");
        },
        onError: (err) => toast.error(apiErrorMessage(err)),
      },
    );
  };

  const submitField = (e: React.FormEvent) => {
    e.preventDefault();
    if (categoryId === "") {
      toast.error("Chọn nhóm");
      return;
    }
    createField.mutate(
      {
        category_id: Number(categoryId),
        field_key: fieldKey,
        label,
        data_type: dataType,
        options:
          dataType === "SELECT"
            ? optionsCsv.split(",").map((s) => s.trim()).filter(Boolean)
            : null,
        is_required: isRequired,
        is_encrypted: isEncrypted,
      },
      {
        onSuccess: () => {
          toast.success("Đã tạo trường");
          setFieldKey("");
          setLabel("");
          setOptionsCsv("");
        },
        onError: (err) => toast.error(apiErrorMessage(err)),
      },
    );
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Trường hồ sơ động</h1>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Tạo nhóm trường</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={submitCategory} className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="cat-code">Mã nhóm</Label>
                <Input id="cat-code" value={catCode} onChange={(e) => setCatCode(e.target.value)} required />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="cat-name">Tên nhóm</Label>
                <Input id="cat-name" value={catName} onChange={(e) => setCatName(e.target.value)} required />
              </div>
              <Button type="submit" disabled={createCategory.isPending}>
                Thêm nhóm
              </Button>
            </form>
            <div className="mt-4 text-sm text-muted-foreground">
              Nhóm hiện có: {categories.data?.map((c) => c.name).join(", ") || "—"}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Tạo trường</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={submitField} className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="cat">Nhóm</Label>
                <select
                  id="cat"
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={categoryId}
                  onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : "")}
                >
                  <option value="">— Chọn nhóm —</option>
                  {categories.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="fk">Khóa (field_key)</Label>
                <Input id="fk" value={fieldKey} onChange={(e) => setFieldKey(e.target.value)} required />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="lb">Nhãn</Label>
                <Input id="lb" value={label} onChange={(e) => setLabel(e.target.value)} required />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="dt">Kiểu dữ liệu</Label>
                <select
                  id="dt"
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={dataType}
                  onChange={(e) => setDataType(e.target.value as ProfileFieldMeta["data_type"])}
                >
                  {DATA_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
              {dataType === "SELECT" && (
                <div className="space-y-1.5">
                  <Label htmlFor="opts">Options (phân tách bởi dấu phẩy)</Label>
                  <Input id="opts" value={optionsCsv} onChange={(e) => setOptionsCsv(e.target.value)} />
                </div>
              )}
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={isRequired} onChange={(e) => setIsRequired(e.target.checked)} />
                Bắt buộc
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={isEncrypted} onChange={(e) => setIsEncrypted(e.target.checked)} />
                Mã hóa (chỉ HR xem)
              </label>
              <Button type="submit" disabled={createField.isPending}>
                Thêm trường
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Danh sách trường</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable
            columns={fieldColumns}
            data={fields.data ?? []}
            page={1}
            pageSize={(fields.data ?? []).length || 1}
            total={(fields.data ?? []).length}
            onPageChange={() => undefined}
            isLoading={fields.isLoading}
          />
        </CardContent>
      </Card>
    </div>
  );
}
