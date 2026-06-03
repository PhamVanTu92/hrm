# PHẦN 4 — KIẾN TRÚC FRONTEND

---

## 4.1. Lựa chọn framework

| Tiêu chí | **Next.js (React) — chọn** | Vue/Nuxt | React SPA (Vite) |
|---|---|---|---|
| Hệ sinh thái form/table động | Rất giàu (RHF, TanStack) | Tốt | Giàu |
| SSR/SEO (HRM nội bộ ít cần) | Có (tùy chọn) | Có | Không |
| Tuyển dev (VN) | Nhiều nhất | Khá | Nhiều |
| Tích hợp RBAC/middleware | Middleware routing tốt | Tốt | Tự lo |

**Chọn Next.js (App Router) + TypeScript** — chủ yếu dùng client-side rendering cho dashboard nội bộ, nhưng tận dụng middleware auth + cấu trúc rõ ràng. Nếu team thuần SPA, Vite+React cũng hợp lệ (cùng pattern).

## 4.2. Stack FE đề xuất

| Nhu cầu | Lib | Lý do |
|---|---|---|
| Data fetching/cache | **TanStack Query** | Cache, invalidation, retry — hợp REST envelope |
| Server/client state | TanStack Query + **Zustand** (UI state) | Tránh Redux nặng; Zustand nhẹ cho auth/UI |
| Form | **React Hook Form + Zod** | Form động hiệu năng cao, validate schema |
| Table | **TanStack Table** | Headless, server-side pagination/sort/filter |
| UI | **shadcn/ui + Tailwind** | Component chủ động, dễ tùy biến, accessible |
| Chart/Dashboard | Recharts / ECharts | Biểu đồ lương/chấm công |
| HTTP | axios (interceptor refresh token) | Interceptor xử lý 401→refresh |

## 4.3. Folder structure

```
hrm-frontend/
├── src/
│   ├── app/                       # Next App Router
│   │   ├── (auth)/login/
│   │   ├── (dashboard)/
│   │   │   ├── employees/
│   │   │   ├── attendance/
│   │   │   ├── approvals/
│   │   │   ├── payroll/
│   │   │   ├── payslips/
│   │   │   └── settings/dynamic-fields/
│   │   └── layout.tsx
│   ├── components/
│   │   ├── ui/                    # shadcn primitives
│   │   ├── data-table/            # TanStack Table wrapper (server-side)
│   │   └── dynamic-form/          # render form từ metadata field
│   ├── features/                  # theo module (mirror backend)
│   │   ├── auth/                  # hooks, api, store
│   │   ├── employee/
│   │   ├── payroll/
│   │   └── ...
│   ├── lib/
│   │   ├── api-client.ts          # axios + interceptor refresh
│   │   ├── query-client.ts
│   │   └── rbac.ts                # hasPermission(user, perm)
│   ├── hooks/
│   ├── stores/                    # zustand: authStore, uiStore
│   └── types/                     # types khớp schema BE
```

## 4.4. Component strategy

- **DynamicForm**: nhận `fields[]` metadata từ `/dynamic-fields` → render input theo `data_type`, áp validation Zod sinh động, field `is_encrypted` hiển thị icon khóa + chỉ HR thấy giá trị.
- **DataTable** generic: nhận `columns`, gọi API server-side (page/sort/filter sync với URL query) → đồng nhất mọi danh sách (employees, payroll items, audit).
- **Feature-based**: mỗi feature có `api.ts` (call endpoint), `hooks.ts` (useQuery/useMutation), `components/`.

```tsx
// components/dynamic-form/DynamicForm.tsx (rút gọn)
export function DynamicForm({ fields, defaultValues, onSubmit }: Props) {
  const schema = buildZodSchema(fields);            // sinh Zod từ metadata
  const form = useForm({ resolver: zodResolver(schema), defaultValues });
  return (
    <form onSubmit={form.handleSubmit(onSubmit)}>
      {fields.map(f => <FieldRenderer key={f.field_key} field={f} form={form} />)}
    </form>
  );
}
// FieldRenderer: switch f.data_type → Input/NumberInput/DatePicker/Select/Switch
```

## 4.5. RBAC UI

- Sau login, `/auth/me` trả `perms[]` → lưu authStore.
- `<Can perm="payroll:run">...</Can>` wrapper ẩn/hiện nút.
- Next.js middleware chặn route theo perm (defense-in-depth — **backend vẫn là nguồn enforce thật**).

```tsx
export function Can({ perm, children }: { perm: string; children: ReactNode }) {
  const perms = useAuthStore(s => s.perms);
  return perms.includes(perm) ? <>{children}</> : null;
}
```

## 4.6. API integration & authentication handling

```ts
// lib/api-client.ts
const api = axios.create({ baseURL: "/api/v1", withCredentials: true });

// gắn access token
api.interceptors.request.use(cfg => {
  const t = useAuthStore.getState().accessToken;
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

// auto refresh khi 401 (rotation)
let refreshing: Promise<string> | null = null;
api.interceptors.response.use(r => r, async err => {
  if (err.response?.status === 401 && !err.config._retry) {
    err.config._retry = true;
    refreshing ??= refreshToken();                  // dedupe nhiều request 401 cùng lúc
    const newToken = await refreshing; refreshing = null;
    err.config.headers.Authorization = `Bearer ${newToken}`;
    return api(err.config);
  }
  return Promise.reject(err);
});
```

- **Access token** giữ trong memory (Zustand), **refresh token** trong HttpOnly Secure cookie (XSS-safe).
- Envelope `{data, meta}` → unwrap ở api layer; lỗi `{error:{code,message}}` → toast theo `code`.

## 4.7. Dashboard architecture
- HR dashboard: tổng quan công tháng, NV đi muộn, kỳ lương trạng thái, đơn chờ duyệt.
- Manager: inbox duyệt, NV phòng mình.
- Employee: chấm công cá nhân, đơn từ, phiếu lương.
- Lazy-load chart, server-side aggregate (không kéo raw về FE).

→ Tiếp: [Phần 5 — DevOps & Deployment](05-devops.md).
