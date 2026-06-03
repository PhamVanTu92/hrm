"use client";

import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";

import { Can } from "@/components/can";
import { DataTable } from "@/components/data-table/data-table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuditLogs } from "@/features/audit/hooks";
import type { AuditLog } from "@/types/audit";

const columns: ColumnDef<AuditLog>[] = [
  {
    accessorKey: "created_at",
    header: "Thời gian",
    cell: ({ row }) => new Date(row.original.created_at).toLocaleString("vi-VN"),
  },
  { accessorKey: "action", header: "Hành động" },
  { accessorKey: "entity", header: "Đối tượng" },
  { accessorKey: "entity_id", header: "ID" },
  { accessorKey: "actor_id", header: "Người thực hiện" },
];

function AuditViewer() {
  const [page, setPage] = useState(1);
  const [entity, setEntity] = useState("");
  const [entityId, setEntityId] = useState("");
  const [action, setAction] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const { data, isLoading } = useAuditLogs({
    page,
    size: 20,
    entity: entity || undefined,
    entity_id: entityId || undefined,
    action: action || undefined,
    date_from: from ? new Date(from).toISOString() : undefined,
    date_to: to ? new Date(to).toISOString() : undefined,
  });

  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-5">
        <Input placeholder="entity (vd employees)" value={entity} onChange={(e) => setEntity(e.target.value)} />
        <Input placeholder="entity_id" value={entityId} onChange={(e) => setEntityId(e.target.value)} />
        <Input placeholder="action" value={action} onChange={(e) => setAction(e.target.value)} />
        <Input type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} />
        <Input type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} />
      </div>
      <Button variant="outline" size="sm" onClick={() => setPage(1)}>
        Lọc
      </Button>
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

export default function AuditPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Nhật ký kiểm toán</h1>
      <Can
        perm="audit:read"
        fallback={<p className="text-sm text-muted-foreground">Bạn không có quyền xem audit.</p>}
      >
        <AuditViewer />
      </Can>
    </div>
  );
}
