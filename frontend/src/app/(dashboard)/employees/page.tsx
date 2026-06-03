"use client";

import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";

import { Can } from "@/components/can";
import { DataTable } from "@/components/data-table/data-table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useEmployees } from "@/features/employee/hooks";
import type { Employee } from "@/types/employee";

const columns: ColumnDef<Employee>[] = [
  { accessorKey: "employee_code", header: "Mã NV" },
  { accessorKey: "full_name", header: "Họ tên" },
  { accessorKey: "status", header: "Trạng thái" },
  {
    accessorKey: "join_date",
    header: "Ngày vào",
    cell: ({ row }) => row.original.join_date ?? "—",
  },
];

export default function EmployeesPage() {
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const { data, isLoading } = useEmployees({ page, size: 20, q: q || undefined });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Nhân viên</h1>
        <Can perm="employee:write">
          <Button>Thêm nhân viên</Button>
        </Can>
      </div>

      <Input
        placeholder="Tìm theo tên…"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setPage(1);
        }}
        className="max-w-xs"
      />

      <DataTable
        columns={columns}
        data={data?.data ?? []}
        page={page}
        pageSize={20}
        total={data?.meta.total ?? 0}
        onPageChange={setPage}
        isLoading={isLoading}
      />
    </div>
  );
}
