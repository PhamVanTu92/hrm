"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";

import { Can } from "@/components/can";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  useCalculateRun,
  useComponents,
  useCreateComponent,
  useCreatePeriod,
  useCreateRun,
  useImportInput,
  useLockRun,
} from "@/features/payroll/hooks";
import { templateUrl } from "@/features/payroll/api";
import { apiErrorMessage } from "@/lib/api-client";
import type { ImportReport } from "@/types/payroll";

function ComponentsCard() {
  const components = useComponents();
  const create = useCreateComponent();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [valueType, setValueType] = useState<"INPUT" | "FIXED" | "FORMULA">("INPUT");
  const [expression, setExpression] = useState("");
  const [defaultValue, setDefaultValue] = useState("");

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    create.mutate(
      {
        code,
        name,
        value_type: valueType,
        expression: valueType === "FORMULA" ? expression : undefined,
        default_value: valueType === "FIXED" ? defaultValue : undefined,
      },
      {
        onSuccess: () => {
          toast.success("Đã tạo khoản lương");
          setCode("");
          setName("");
          setExpression("");
          setDefaultValue("");
        },
        onError: (err) => toast.error(apiErrorMessage(err)),
      },
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Khoản lương / công thức</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Can perm="payroll:run">
          <form onSubmit={onSubmit} className="grid gap-3 sm:grid-cols-2">
            <Input placeholder="Mã (code)" value={code} onChange={(e) => setCode(e.target.value)} required />
            <Input placeholder="Tên" value={name} onChange={(e) => setName(e.target.value)} required />
            <select
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={valueType}
              onChange={(e) => setValueType(e.target.value as "INPUT" | "FIXED" | "FORMULA")}
            >
              <option value="INPUT">INPUT (import Excel)</option>
              <option value="FIXED">FIXED (giá trị cố định)</option>
              <option value="FORMULA">FORMULA (biểu thức)</option>
            </select>
            {valueType === "FORMULA" && (
              <Input
                placeholder="Biểu thức, vd luong_cung * 0.1"
                value={expression}
                onChange={(e) => setExpression(e.target.value)}
              />
            )}
            {valueType === "FIXED" && (
              <Input
                placeholder="Giá trị mặc định"
                value={defaultValue}
                onChange={(e) => setDefaultValue(e.target.value)}
              />
            )}
            <div className="sm:col-span-2">
              <Button type="submit" disabled={create.isPending}>
                Thêm khoản
              </Button>
            </div>
          </form>
        </Can>

        <ul className="space-y-1 text-sm">
          {components.data?.map((c) => (
            <li key={c.id} className="flex justify-between border-b py-1">
              <span>
                <code>{c.var_code}</code> — {c.name}
              </span>
              <span className="text-muted-foreground">
                {c.value_type}
                {c.expression ? `: ${c.expression}` : ""}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function ExcelImportCard() {
  const importInput = useImportInput();
  const [period, setPeriod] = useState("2026-05");
  const [report, setReport] = useState<ImportReport | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const onImport = (e: React.FormEvent) => {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) {
      toast.error("Chọn file .xlsx");
      return;
    }
    importInput.mutate(
      { period, file },
      {
        onSuccess: (r) => {
          setReport(r);
          toast.success(`Import xong: ${r.ok} dòng OK, ${r.errors.length} lỗi`);
        },
        onError: (err) => toast.error(apiErrorMessage(err)),
      },
    );
  };

  return (
    <Can perm="payroll:run">
      <Card>
        <CardHeader>
          <CardTitle>Import dữ liệu lương (Excel)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="period">Kỳ (YYYY-MM)</Label>
            <Input id="period" value={period} onChange={(e) => setPeriod(e.target.value)} className="max-w-[160px]" />
          </div>
          <Button variant="outline" size="sm" asChild>
            <a href={templateUrl(period)}>Tải template</a>
          </Button>
          <form onSubmit={onImport} className="flex items-center gap-2">
            <input ref={fileRef} type="file" accept=".xlsx" className="text-sm" />
            <Button type="submit" disabled={importInput.isPending}>
              Import
            </Button>
          </form>
          {report && (
            <div className="text-sm">
              <p className="text-green-600">OK: {report.ok} dòng</p>
              {report.errors.length > 0 && (
                <ul className="mt-1 list-inside list-disc text-destructive">
                  {report.errors.map((er, i) => (
                    <li key={i}>
                      Dòng {er.row}: {er.error}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </Can>
  );
}

function RunCard() {
  const createPeriod = useCreatePeriod();
  const createRun = useCreateRun();
  const calculate = useCalculateRun();
  const lock = useLockRun();
  const [period, setPeriod] = useState("2026-05");
  const [runId, setRunId] = useState<number | null>(null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Kỳ tính lương</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-end gap-2">
          <div className="space-y-1.5">
            <Label htmlFor="rp">Kỳ</Label>
            <Input id="rp" value={period} onChange={(e) => setPeriod(e.target.value)} className="w-[140px]" />
          </div>
          <Can perm="payroll:run">
            <Button
              variant="outline"
              onClick={() =>
                createPeriod.mutate(period, {
                  onSuccess: () => toast.success("Đã mở kỳ"),
                  onError: (err) => toast.error(apiErrorMessage(err)),
                })
              }
            >
              Mở kỳ
            </Button>
            <Button
              onClick={() =>
                createRun.mutate(period, {
                  onSuccess: (r) => {
                    setRunId(r.id);
                    toast.success(`Đã tạo run #${r.id}`);
                  },
                  onError: (err) => toast.error(apiErrorMessage(err)),
                })
              }
            >
              Tạo bảng tính
            </Button>
          </Can>
        </div>

        {runId && (
          <div className="flex items-center gap-2">
            <span className="text-sm">Run #{runId}</span>
            <Can perm="payroll:run">
              <Button
                size="sm"
                onClick={() =>
                  calculate.mutate(runId, {
                    onSuccess: (r) => toast.success(`Đã tính ${r.calculated} NV`),
                    onError: (err) => toast.error(apiErrorMessage(err)),
                  })
                }
              >
                Tính lương
              </Button>
            </Can>
            <Can perm="payroll:lock">
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  lock.mutate(runId, {
                    onSuccess: () => toast.success("Đã khóa kỳ"),
                    onError: (err) => toast.error(apiErrorMessage(err)),
                  })
                }
              >
                Khóa kỳ
              </Button>
            </Can>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function PayrollPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Bảng lương</h1>
      <div className="grid gap-6 lg:grid-cols-2">
        <ComponentsCard />
        <ExcelImportCard />
      </div>
      <RunCard />
    </div>
  );
}
