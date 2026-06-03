# PHẦN 2B — AUTHENTICATION, SECURITY & API DESIGN

---

## 2.3. Authentication & Security

### 2.3.1. Thư viện đề xuất

| Nhu cầu | Thư viện | Lý do |
|---|---|---|
| JWT | `pyjwt` (hoặc `python-jose`) | Chuẩn, nhẹ; pyjwt ít CVE hơn jose |
| Password hash | `argon2-cffi` (Argon2id) | Thắng PHC 2015, kháng GPU/ASIC tốt hơn bcrypt; fallback bcrypt qua `passlib` nếu cần |
| AES-256 | `cryptography` (AESGCM) | Lib chuẩn, AEAD (mã hóa + xác thực toàn vẹn) |
| Rate limit | `slowapi` + Redis | Tích hợp FastAPI, backend Redis cho multi-instance |
| Settings | `pydantic-settings` | Validate env var, type-safe |
| Secret mgmt | env var + Docker secret / Vault (prod lớn) | Không hardcode |

### 2.3.2. Flow login (sequence)

```
Client                      FastAPI                       Redis        Postgres
  │  POST /auth/login          │                            │            │
  │  {username,password}       │                            │            │
  │ ─────────────────────────► │                            │            │
  │                            │ check rate-limit (ip+user) ─►│            │
  │                            │◄── ok / 429 ───────────────│            │
  │                            │ SELECT user by username ───────────────►│
  │                            │◄── user row ───────────────────────────│
  │                            │ verify Argon2(password, hash)           │
  │                            │ if fail: failed_attempts++; audit;      │
  │                            │   lock if >=5  → 423/401                │
  │                            │ if ok: reset attempts                   │
  │                            │ issue access JWT (15m) + refresh (7d)   │
  │                            │ store SHA256(refresh) ─────────────────►│ refresh_tokens
  │ ◄── 200 {access, refresh} ─│                                         │
```

**Token lifecycle:**

| Token | TTL | Lưu ở đâu | Thu hồi |
|---|---|---|---|
| Access JWT | 15 phút | Client (memory/HttpOnly cookie) | Không revoke (ngắn hạn); claim `jti`, `roles`, `perms` |
| Refresh token | 7 ngày | Client (HttpOnly Secure cookie) + hash ở DB | Revoke = set `revoked_at`; rotation mỗi lần refresh |

**Refresh rotation (chống replay):** mỗi lần `/auth/refresh` → cấp refresh mới, revoke cái cũ. Nếu nhận refresh đã `revoked_at` → nghi ngờ token bị đánh cắp → revoke toàn bộ token user đó.

```python
# core/security.py (rút gọn)
import jwt, os, hashlib
from argon2 import PasswordHasher
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from datetime import datetime, timedelta, timezone

ph = PasswordHasher()                       # Argon2id, tham số mặc định OWASP
JWT_SECRET = os.environ["JWT_SECRET_KEY"]   # >= 32 bytes random
AES_KEY    = bytes.fromhex(os.environ["AES_KEY_HEX"])  # 32 bytes = AES-256

def hash_password(pw: str) -> str: return ph.hash(pw)
def verify_password(pw: str, h: str) -> bool:
    try: return ph.verify(h, pw)
    except Exception: return False

def create_access_token(sub: str, roles: list[str], perms: list[str]) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": sub, "roles": roles, "perms": perms,
               "iat": now, "exp": now + timedelta(minutes=15),
               "jti": os.urandom(8).hex(), "typ": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

# ===== AES-256-GCM: nonce(12) | ciphertext | tag(16) =====
def encrypt(plaintext: str) -> bytes:
    nonce = os.urandom(12)
    ct = AESGCM(AES_KEY).encrypt(nonce, plaintext.encode(), None)
    return nonce + ct                         # lưu BYTEA

def decrypt(blob: bytes) -> str:
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(AES_KEY).decrypt(nonce, ct, None).decode()

def hash_token(raw: str) -> str:              # cho refresh token
    return hashlib.sha256(raw.encode()).hexdigest()
```

### 2.3.3. RBAC & permission checking

**Mô hình:** `user → roles → permissions`. Permission dạng `"<resource>:<action>"` (vd `payroll:read`, `employee:write`, `salary:view_sensitive`).

```python
# permissions/catalog.py
PERMISSIONS = {
    "employee:read", "employee:write",
    "salary:view_sensitive",          # xem lương đã giải mã → AUDIT bắt buộc
    "payroll:read", "payroll:run", "payroll:lock",
    "attendance:read", "attendance:manage",
    "approval:act", "dynamic_field:manage", "audit:read",
}

# api/deps.py
from fastapi import Depends, HTTPException, status

def require_perm(*needed: str):
    async def checker(user = Depends(get_current_user)):
        user_perms = set(user.perms)          # lấy từ JWT claim
        if not set(needed).issubset(user_perms):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Thiếu quyền")
        return user
    return checker

# Dùng trong endpoint:
# @router.get("/payroll/{id}", dependencies=[Depends(require_perm("payroll:read"))])
```

**Object-level (row) check** khi cần (vd manager chỉ xem NV phòng mình): kiểm tra trong service, không chỉ permission tĩnh.

```python
def can_view_employee(actor, target_emp) -> bool:
    if "employee:read_all" in actor.perms: return True
    if actor.is_manager and target_emp.department_id == actor.department_id: return True
    return actor.employee_id == target_emp.id     # tự xem mình
```

**Row-Level Security (Postgres RLS)** — dùng cho bảng đặc biệt nhạy cảm nếu muốn defense-in-depth, nhưng với HRM nội bộ chủ yếu enforce ở tầng service. Khuyến nghị bật RLS cho `payroll_run_items` ở môi trường nhiều DBA.

### 2.3.4. Anti-bruteforce & rate limiting

| Lớp | Cơ chế |
|---|---|
| Per-account | `failed_attempts` ≥ 5 → khóa 15 phút (`is_locked` + timestamp). Reset khi login thành công. |
| Per-IP | `slowapi`: `/auth/login` giới hạn 10 req/phút/IP (Redis backend) |
| Global API | 300 req/phút/user mặc định; endpoint nặng (payroll run, export) giới hạn riêng |
| CAPTCHA | Sau 3 lần fail liên tiếp (tùy chọn, frontend) |
| Audit | Mọi login fail ghi `login_attempts` + alert nếu spike |

```python
# middleware/rate_limit.py
from slowapi import Limiter
from slowapi.util import get_remote_address
limiter = Limiter(key_func=get_remote_address, storage_uri="redis://redis:6379/1")
# @limiter.limit("10/minute") trên route /auth/login
```

### 2.3.5. Secret & key management

- **AES key & JWT secret**: env var, inject qua Docker secret / Vault. KHÔNG commit, KHÔNG để trong image.
- **Key rotation AES**: thêm `key_version` byte đầu ciphertext → giải mã chọn key theo version, mã hóa mới bằng key mới. Re-encrypt nền khi rotate.
- `.env` chỉ dùng dev; prod dùng orchestrator secret.

### 2.3.6. Database-level encryption tổng hợp

- App-layer AES-256-GCM cho cột `enc_*` (đã mô tả). Lập trình viên/DBA SELECT thẳng chỉ thấy BYTEA.
- TLS bắt buộc giữa app↔Postgres (`sslmode=require`).
- Backup file cũng chứa ciphertext → rò rỉ backup vẫn an toàn. Backup được mã hóa thêm ở tầng storage (xem Phần 5).
- Xem lương giải mã → cần `salary:view_sensitive` + ghi `audit_logs(action=VIEW_SENSITIVE)`.

---

## 2.4. API Design (REST chuẩn)

### 2.4.1. Quy ước chung

- **Versioning**: prefix path `/api/v1/...`. Breaking change → `/api/v2`.
- **Envelope response** thống nhất:

```jsonc
// success
{ "data": {...}, "meta": {...} }
// list
{ "data": [...], "meta": {"page":1,"size":20,"total":135,"pages":7} }
// error
{ "error": {"code":"PAYROLL_LOCKED","message":"Kỳ lương đã khóa","details":{...}} }
```

- **Pagination**: `?page=1&size=20` (size max 100). Trả `meta`.
- **Filtering**: `?department_id=3&status=ACTIVE&q=nguyen` (q = full-text/trgm).
- **Sorting**: `?sort=-created_at,full_name` (`-` = desc).
- **Idempotency**: POST tạo payroll/run hỗ trợ header `Idempotency-Key`.
- **HTTP status**: 200/201/204, 400 (validate), 401, 403, 404, 409 (conflict/locked), 422 (Pydantic), 429, 500.

```python
# core/pagination.py
from pydantic import BaseModel
from typing import Generic, TypeVar
T = TypeVar("T")
class PageMeta(BaseModel):
    page:int; size:int; total:int; pages:int
class Page(BaseModel, Generic[T]):
    data: list[T]; meta: PageMeta
```

### 2.4.2. Error handling strategy

```python
# core/exceptions.py
class DomainError(Exception):
    code = "DOMAIN_ERROR"; status = 400
    def __init__(self, message, details=None): self.message=message; self.details=details or {}
class PayrollLocked(DomainError): code="PAYROLL_LOCKED"; status=409
class PermissionDenied(DomainError): code="FORBIDDEN"; status=403

# main.py handler
@app.exception_handler(DomainError)
async def domain_handler(req, exc: DomainError):
    return JSONResponse(status_code=exc.status,
        content={"error":{"code":exc.code,"message":exc.message,"details":exc.details}})
```

- Pydantic `ValidationError` → 422 envelope chuẩn hóa.
- Lỗi không lường (500) → log `request_id`, KHÔNG lộ stacktrace ra client.

### 2.4.3. Endpoint list theo module

**Auth**
| Method | Path | Mô tả | Quyền |
|---|---|---|---|
| POST | `/api/v1/auth/login` | Đăng nhập | public (rate-limit) |
| POST | `/api/v1/auth/refresh` | Rotate refresh → access mới | refresh cookie |
| POST | `/api/v1/auth/logout` | Revoke refresh | auth |
| GET | `/api/v1/auth/me` | Thông tin user + perms | auth |
| POST | `/api/v1/auth/change-password` | Đổi mật khẩu | auth |

**Employee + Dynamic Profile**
| Method | Path | Mô tả | Quyền |
|---|---|---|---|
| GET | `/api/v1/employees` | List (page/filter/sort) | employee:read |
| POST | `/api/v1/employees` | Tạo NV | employee:write |
| GET | `/api/v1/employees/{id}` | Chi tiết (sensitive ẩn) | employee:read |
| GET | `/api/v1/employees/{id}/sensitive` | Xem CCCD/lương giải mã | salary:view_sensitive (AUDIT) |
| PATCH | `/api/v1/employees/{id}` | Cập nhật | employee:write |
| GET | `/api/v1/employees/{id}/profile` | Hồ sơ động | employee:read |
| PUT | `/api/v1/employees/{id}/profile` | Lưu hồ sơ động | employee:write |
| GET | `/api/v1/dynamic-fields` | Danh mục + field config | auth |
| POST | `/api/v1/dynamic-fields/categories` | Tạo category | dynamic_field:manage |
| POST | `/api/v1/dynamic-fields/fields` | Tạo field | dynamic_field:manage |

**Attendance**
| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/v1/attendance/daily?employee_id=&from=&to=` | Công ngày |
| GET | `/api/v1/attendance/monthly?period=&department_id=` | Tổng hợp tháng |
| POST | `/api/v1/attendance/recompute` | Tính lại 1 NV/ngày (manage) |
| POST | `/api/v1/attendance/import` | Trigger pull thủ công (manage) |
| PATCH | `/api/v1/attendance/daily/{id}` | Sửa tay (manage, audit) |

**Leave / Approval**
| Method | Path | Mô tả |
|---|---|---|
| POST | `/api/v1/leaves` | Tạo đơn nghỉ |
| GET | `/api/v1/leaves?status=&employee_id=` | List đơn |
| POST | `/api/v1/benefits` | Đăng ký chế độ + file đính kèm |
| GET | `/api/v1/approvals/inbox` | Đơn chờ tôi duyệt |
| POST | `/api/v1/approvals/{instance_id}/approve` | Duyệt |
| POST | `/api/v1/approvals/{instance_id}/reject` | Từ chối + lý do |
| POST | `/api/v1/leaves/{id}/cancel` | Hủy đơn |

**Salary Components**
| Method | Path | Mô tả |
|---|---|---|
| GET/POST | `/api/v1/salary-components` | List/tạo khoản (auto-gen var_code) |
| POST | `/api/v1/salary-components/{id}/assignments` | Gán scope ALL/DEPT/POS/EMP |

**Payroll**
| Method | Path | Mô tả | Quyền |
|---|---|---|---|
| POST | `/api/v1/payroll/periods/{period}/formulas` | Lưu công thức | payroll:run |
| POST | `/api/v1/payroll/periods/{period}/inputs/import` | Import Excel phát sinh | payroll:run |
| POST | `/api/v1/payroll/runs` | Tạo run (async, Celery) | payroll:run |
| GET | `/api/v1/payroll/runs/{id}` | Trạng thái + tiến độ | payroll:read |
| GET | `/api/v1/payroll/runs/{id}/items?department_id=` | Bảng lương | payroll:read |
| POST | `/api/v1/payroll/runs/{id}/lock` | Khóa + snapshot | payroll:lock |
| POST | `/api/v1/payroll/runs/{id}/recalc` | Tính lại (chỉ khi DRAFT) | payroll:run |
| POST | `/api/v1/payroll/runs/{id}/cancel` | Hủy/rollback | payroll:lock |

**Payslip**
| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/v1/payslips/me?period=` | Xem phiếu của tôi |
| POST | `/api/v1/payslips/{id}/confirm` | NV xác nhận → trigger gen+gửi |
| POST | `/api/v1/payslips/{id}/feedback` | Phản hồi sai sót |
| GET | `/api/v1/payslips/{id}/download` | Tải PDF (presigned) |

**Notifications**
| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/v1/notifications?unread=true` | List |
| POST | `/api/v1/notifications/{id}/read` | Đánh dấu đã đọc |
| POST | `/api/v1/notifications/read-all` | Đọc tất cả |

### 2.4.4. Ví dụ request/response schema (Pydantic)

```python
# modules/employee/schemas.py
class EmployeeCreate(BaseModel):
    employee_code: str
    full_name: str = Field(min_length=2, max_length=200)
    department_id: int | None = None
    position_id: int | None = None
    manager_id: int | None = None
    join_date: date | None = None
    national_id: str | None = None      # plaintext vào, mã hóa khi lưu
    phone: str | None = None
    bank_account: str | None = None
    base_salary: Decimal | None = None

class EmployeeOut(BaseModel):
    id: int
    employee_code: str
    full_name: str
    department_id: int | None
    status: str
    # KHÔNG expose sensitive ở đây; có endpoint riêng /sensitive
    model_config = ConfigDict(from_attributes=True)

class EmployeeSensitiveOut(BaseModel):  # chỉ trả khi có quyền + đã audit
    national_id: str | None
    phone: str | None
    bank_account: str | None
    base_salary: Decimal | None
```

```python
# api/v1/employees.py
@router.get("/{id}", response_model=Envelope[EmployeeOut])
async def get_employee(id: int, db=Depends(get_db),
                       user=Depends(require_perm("employee:read"))):
    emp = await EmployeeService(db).get(id)
    if not emp: raise HTTPException(404, "Không tìm thấy nhân viên")
    return {"data": EmployeeOut.model_validate(emp)}

@router.get("/{id}/sensitive", response_model=Envelope[EmployeeSensitiveOut])
async def get_sensitive(id: int, request: Request, db=Depends(get_db),
                        user=Depends(require_perm("salary:view_sensitive"))):
    data = await EmployeeService(db).get_sensitive(id, actor=user, ip=request.client.host)
    # service tự ghi audit_logs(action=VIEW_SENSITIVE)
    return {"data": data}
```

→ Tiếp: [Phần 3 — Phân tích chi tiết từng module](03-modules.md).
