"use client";

import { useParams } from "next/navigation";
import { toast } from "sonner";

import { DynamicForm } from "@/components/dynamic-form/dynamic-form";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useProfileFields, useProfile, useSaveProfile } from "@/features/dynamic-field/hooks";
import { apiErrorMessage } from "@/lib/api-client";
import { hasPermission } from "@/lib/rbac";
import { useAuthStore } from "@/stores/auth-store";

export default function EmployeeProfilePage() {
  const params = useParams<{ id: string }>();
  const employeeId = Number(params.id);
  const user = useAuthStore((s) => s.user);
  const canViewEncrypted = hasPermission(user, "salary:view_sensitive");

  const fields = useProfileFields();
  const profile = useProfile(employeeId);
  const save = useSaveProfile(employeeId);

  if (fields.isLoading || profile.isLoading) {
    return <p className="text-muted-foreground">Đang tải…</p>;
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Hồ sơ động · NV #{employeeId}</h1>
      <Card>
        <CardHeader>
          <CardTitle>Thông tin mở rộng</CardTitle>
        </CardHeader>
        <CardContent>
          {fields.data && fields.data.length ? (
            <DynamicForm
              fields={fields.data}
              defaultValues={profile.data?.data ?? {}}
              canViewEncrypted={canViewEncrypted}
              onSubmit={(values) =>
                save.mutate(values, {
                  onSuccess: () => toast.success("Đã lưu hồ sơ"),
                  onError: (err) => toast.error(apiErrorMessage(err)),
                })
              }
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              Chưa có trường động nào. Tạo ở mục Cấu hình → Trường hồ sơ động.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
