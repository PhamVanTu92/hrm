# PHẦN 1 — TỔNG QUAN KIẾN TRÚC HỆ THỐNG HRM

> Tài liệu triển khai production-ready. Stack: **FastAPI (Python 3.12) + PostgreSQL 16 + Redis 7 + Celery**.
> Đối tượng: dev team có thể bắt đầu coding ngay sau khi đọc.

---

## 1.1. Phân tích bài toán & ràng buộc kiến trúc

| Đặc tính nghiệp vụ | Hệ quả kiến trúc |
|---|---|
| Dữ liệu nhân sự cực nhạy cảm (lương, CCCD, bank) | Mã hóa AES-256 tầng app, audit immutable, RBAC chặt từ API |
| Hồ sơ động (HR tự thêm trường runtime) | Lưu JSONB + metadata-driven, KHÔNG migrate schema mỗi lần thêm field |
| Payroll engine công thức động | Expression evaluator an toàn (sandbox), dependency graph, snapshot bất biến |
| Chấm công kéo log hằng đêm (cron 23:00) | Batch worker tách biệt, idempotent, xử lý raw log lớn |
| Phê duyệt đa cấp động | Workflow/state-machine engine, không hardcode chain |
| Quy mô 100 → 10,000 nhân viên | Scale theo chiều ngang ở tầng worker + read replica DB |

**Kết luận quan trọng:** đây KHÔNG phải hệ CRUD đơn giản. Hai module "xương sống" cần đầu tư nhất là **Dynamic Payroll Engine** và **Attendance batch pipeline**. Kiến trúc phải cô lập rủi ro của 2 module này.

---

## 1.2. Lựa chọn mô hình kiến trúc

### So sánh các lựa chọn

| Tiêu chí | Microservices | Monolith truyền thống | **Modular Monolith (chọn)** |
|---|---|---|---|
| Tốc độ dev MVP 10 tuần | Chậm (devops nặng) | Nhanh | **Nhanh** |
| Transaction xuyên module (payroll ↔ attendance) | Khó (saga, eventual consistency) | Dễ (1 DB transaction) | **Dễ (1 DB transaction)** |
| Team size nhỏ (3-6 dev) | Quá tải vận hành | OK nhưng dễ rối | **Tối ưu** |
| Scale tới 10k NV | Tốt | Hạn chế | **Đủ** (scale worker + replica) |
| Tách service sau này | N/A | Khó | **Dễ** (boundary rõ) |

### Quyết định: **Modular Monolith + Clean Architecture (layered) + DDD nhẹ (tactical patterns)**

**Lý do kỹ thuật:**

1. **Modular Monolith thay vì Microservices** — Payroll cần đọc đồng thời attendance, employee, salary_components, approvals trong **một transaction nhất quán**. Tách microservice sẽ buộc dùng saga/2PC → phức tạp không cần thiết cho HRM nội bộ (không có traffic internet-scale). Deploy 1 artifact, vận hành đơn giản, phù hợp team nhỏ + timeline 10 tuần.

2. **Clean Architecture (Layered)** — tách `API → Service (use-case) → Repository → Model`. Lý do: payroll formula logic phải **test được độc lập** với DB và HTTP. Domain logic không phụ thuộc framework.

3. **DDD tactical (không strategic nặng)** — dùng khái niệm *module = bounded context* (employee, attendance, payroll, approval, auth...), mỗi module có ranh giới rõ. KHÔNG áp dụng đầy đủ aggregate/event-sourcing vì over-engineering cho quy mô này. Giao tiếp giữa module qua **service interface + domain events nội bộ** (in-process event bus), KHÔNG gọi thẳng repository của module khác.

**Nguyên tắc ranh giới (enforce qua code review + import-linter):**
- Module A chỉ gọi module B qua `B.services.PublicService` (facade), không import `B.repositories.*` hay `B.models.*` trực tiếp.
- Shared: chỉ `core/` (config, security, db, events) và `schemas` công khai.

---

## 1.3. Sơ đồ kiến trúc tổng thể (ASCII)

```
                              ┌────────────────────────────┐
        HTTPS                 │      NGINX (reverse proxy)  │
   ─────────────────────────► │   TLS termination + WAF     │
                              │   rate-limit L7, gzip       │
                              └─────────────┬──────────────┘
                                            │
                ┌───────────────────────────┼───────────────────────────┐
                │                           │                           │
        ┌───────▼────────┐         ┌────────▼────────┐         ┌────────▼────────┐
        │ FastAPI app #1 │  ...    │ FastAPI app #N  │         │  Frontend SPA   │
        │ (uvicorn/      │         │ (gunicorn       │         │  (Next.js,      │
        │  gunicorn)     │         │  workers)       │         │  static/CDN)    │
        └───────┬────────┘         └────────┬────────┘         └─────────────────┘
                │   API layer (REST /api/v1)│
                │   ┌────────────────────────────────────────────┐
                │   │  MODULES (bounded contexts)                  │
                │   │  auth │ employee │ attendance │ approval     │
                │   │  payroll │ payslip │ notification │ audit     │
                │   │  Service → Repository → SQLAlchemy Model     │
                │   └────────────────────────────────────────────┘
                │                  │                    │
        ┌───────▼──────┐   ┌───────▼───────┐    ┌───────▼────────┐
        │ PostgreSQL16 │   │   Redis 7     │    │  Object store  │
        │  primary     │   │ cache + broker│    │  (MinIO/S3)    │
        │   │          │   │ + rate-limit  │    │  file attach,  │
        │   ▼ (stream) │   └───────┬───────┘    │  payslip PDF   │
        │ read replica │           │            └────────────────┘
        └──────────────┘           │
                          ┌────────▼─────────────────────────────┐
                          │  CELERY WORKERS (tách process/host)   │
                          │  queue: default | payroll | attendance│
                          │         | email | pdf                 │
                          │  ┌─────────────────────────────────┐  │
                          │  │ Celery Beat (scheduler)          │  │
                          │  │  - 23:00 pull attendance logs    │  │
                          │  │  - monthly payroll aggregation   │  │
                          │  │  - escalation approvals          │  │
                          │  └─────────────────────────────────┘  │
                          └────────────────┬──────────────────────┘
                                           │
                          ┌────────────────▼──────────────────────┐
                          │ INTEGRATIONS                            │
                          │ - Máy chấm công (.mdb / SQL Express/IP) │
                          │ - SMTP / email gateway                  │
                          └─────────────────────────────────────────┘
```

---

## 1.4. Luồng dữ liệu tổng thể (end-to-end payroll)

```
[Máy chấm công] --(23:00 cron)--> [attendance.raw_logs] --(normalize)--> [attendance_daily]
                                                                              │
[Đơn từ/chế độ] --(approval engine)--> [leave/benefit approved] ──────────────┤
                                                                              ▼
                                                                  [attendance_monthly] (công thực tế)
                                                                              │
[salary_components + assignments] ──┐                                         │
[Excel phát sinh import]          ──┼──> [Payroll Engine: build var context]  │
[employee base salary (encrypted)]──┘            │                            │
                                                 ▼                            │
                                        [Dependency graph + SimpleEval] <──────┘
                                                 │
                                                 ▼
                                  [payroll_run (DRAFT)] → HR review → [LOCKED + snapshot bất biến]
                                                 │
                                                 ▼  status=CONFIRMED (nhân viên xác nhận)
                                  [Celery: gen PDF → khóa pass (6 số cuối CCCD) → gửi email]
                                                 │
                                                 ▼
                                          [payslips + file_attachments + audit_logs]
```

**Đặc tính then chốt:**
- Payroll đọc snapshot dữ liệu tại thời điểm chốt → tái tính cho ra **kết quả y hệt** (reproducible). Mọi input (công, biến, công thức, base salary) được đóng băng vào `payroll_run_items.input_snapshot (JSONB)`.
- Attendance pipeline **idempotent**: chạy lại cùng ngày không nhân đôi dữ liệu (dùng natural key `(employee_id, work_date, device_id)`).

---

## 1.5. Communication giữa các module

| Cơ chế | Khi nào dùng | Ví dụ |
|---|---|---|
| **Synchronous service call** (in-process) | Cần kết quả ngay, trong cùng request | `PayrollService` gọi `AttendanceService.get_monthly(emp, period)` |
| **Domain events (in-process bus)** | Side-effect không chặn luồng chính | `LeaveApproved` → attendance cập nhật bù công; `PayrollConfirmed` → enqueue PDF |
| **Celery task (async, qua Redis)** | Tác vụ nặng / chạy nền / retry | gen PDF, gửi mail, pull máy chấm công, aggregate tháng |
| **DB như integration point** | Batch lớn | raw_logs → daily → monthly |

**In-process event bus (đơn giản, không cần Kafka):**

```python
# core/events.py
from collections import defaultdict
from typing import Callable

_handlers: dict[type, list[Callable]] = defaultdict(list)

def subscribe(event_type: type):
    def deco(fn):
        _handlers[event_type].append(fn)
        return fn
    return deco

async def publish(event) -> None:
    for h in _handlers[type(event)]:
        await h(event)   # handler tự quyết định: làm ngay hay enqueue Celery

# Ví dụ event
@dataclass(frozen=True)
class LeaveApproved:
    employee_id: int
    period: str        # '2026-05'
    leave_days: float
    leave_type: str
```

> Quy tắc: event handler **không** ném exception làm fail request gốc nếu side-effect là phụ. Side-effect quan trọng (audit) ghi trong cùng transaction.

---

## 1.6. Scalable architecture: 100 → 10,000 nhân viên

| Quy mô | Bottleneck thực tế | Giải pháp |
|---|---|---|
| **100 NV** | Không có | 1 app container + 1 Postgres + 1 Redis + 1 worker. Single VPS 4 vCPU / 8GB. |
| **1,000 NV** | Payroll tháng + PDF hàng loạt | Tách worker queue (`payroll`, `pdf`, `email`). Gunicorn 4 workers. Connection pool (PgBouncer). |
| **5,000 NV** | Read-heavy (dashboard, list), batch payroll | Postgres **read replica** cho query đọc nặng. Partition `attendance_raw_logs` & `audit_logs` theo tháng. Redis cache cho RBAC/permission & master data. |
| **10,000 NV** | Payroll run = 10k phép tính + 10k PDF; attendance 10k×N quét/ngày | Horizontal scale worker (nhiều host). Chia payroll run thành **chunk job** (Celery `group`/`chord`, vd 500 NV/chunk). PDF gen song song. Object store (S3/MinIO) cho file. Beat dùng `RedBeat` (lock chống chạy trùng khi nhiều beat). |

**Quy tắc scale cốt lõi:**
1. **App layer stateless** → scale ngang vô hạn sau Nginx (round-robin). Session/token là JWT stateless.
2. **DB là điểm khó scale nhất** → tách read/write, partition bảng tăng trưởng nhanh (raw_logs, audit_logs, notifications), index đúng.
3. **Tác vụ nặng → worker**, không bao giờ chạy trong request HTTP. Payroll 10k NV chạy bằng chord:

```
payroll_run(period)
  └─ split employees into chunks of 500
       ├─ chunk_task([emp...])  ─┐
       ├─ chunk_task([emp...])   ├─ (parallel across workers)
       └─ chunk_task([emp...])  ─┘
            └─ chord callback: finalize_run() → set status, audit
```

4. **Cache tầng (Redis):** permission resolve, master data (ca, ngày lễ, salary_components def), tỷ giá/hằng số. TTL + invalidation theo event khi HR sửa cấu hình.

---

## 1.7. Tổng kết quyết định kiến trúc (cho dev)

- [x] **Modular Monolith** — 1 codebase, ranh giới module enforce bằng import-linter.
- [x] **Clean/Layered**: `api → service → repository → model`, domain logic độc lập framework.
- [x] **Async FastAPI** cho I/O; **Celery** cho CPU/batch nặng.
- [x] **PostgreSQL primary + read replica**, partition bảng log.
- [x] **Redis**: cache + broker + rate-limit + distributed lock.
- [x] **Object store** cho file & PDF (không nhét BLOB vào DB).
- [x] Mọi tính toán nhạy cảm (payroll) phải **reproducible từ snapshot**.

→ Chi tiết backend ở [Phần 2](02-backend-fastapi.md). Chi tiết từng module ở [Phần 3](03-modules.md).
