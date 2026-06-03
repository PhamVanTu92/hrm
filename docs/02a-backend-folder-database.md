# PHẦN 2A — BACKEND FASTAPI: FOLDER STRUCTURE & DATABASE

---

## 2.1. Folder Structure (production)

```
hrm-backend/
├── pyproject.toml                 # poetry/uv, ruff, mypy config
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── migrations/                    # Alembic
│   └── versions/
├── scripts/
│   ├── seed.py                    # seed roles/permissions/master data
│   └── create_superuser.py
└── app/
    ├── main.py                    # FastAPI app factory, router mount, middleware
    ├── core/                      # hạ tầng dùng chung, KHÔNG chứa business logic
    │   ├── config.py              # Pydantic Settings (env vars)
    │   ├── database.py            # async engine, SessionLocal, get_db dependency
    │   ├── security.py            # JWT, password hash, AES-256 encrypt/decrypt
    │   ├── redis.py               # redis client, cache helpers
    │   ├── events.py              # in-process event bus
    │   ├── exceptions.py          # domain exceptions + handlers
    │   ├── pagination.py          # Page[T], params chuẩn
    │   ├── logging.py             # structlog config (JSON logs)
    │   └── celery_app.py          # Celery instance + queues
    │
    ├── api/                       # tầng HTTP — mỏng, chỉ điều phối
    │   ├── deps.py                # dependencies: current_user, require_perm, db
    │   ├── router.py              # APIRouter gốc, gắn các v1 router
    │   └── v1/
    │       ├── auth.py
    │       ├── employees.py
    │       ├── attendance.py
    │       ├── leaves.py
    │       ├── approvals.py
    │       ├── payroll.py
    │       ├── payslips.py
    │       ├── salary_components.py
    │       ├── dynamic_fields.py
    │       └── notifications.py
    │
    ├── modules/                   # bounded contexts — mỗi module tự chứa
    │   ├── auth/
    │   │   ├── models.py          # SQLAlchemy: User, Role, Permission...
    │   │   ├── schemas.py         # Pydantic request/response
    │   │   ├── repository.py      # truy vấn DB thuần
    │   │   ├── service.py         # use-case / business logic
    │   │   └── events.py          # event định nghĩa & handler của module
    │   ├── employee/
    │   ├── attendance/
    │   ├── approval/
    │   ├── payroll/               # module phức tạp nhất
    │   │   ├── models.py
    │   │   ├── schemas.py
    │   │   ├── repository.py
    │   │   ├── service.py
    │   │   ├── engine/            # formula engine tách riêng để test độc lập
    │   │   │   ├── parser.py
    │   │   │   ├── evaluator.py   # SimpleEval wrapper an toàn
    │   │   │   ├── graph.py       # dependency graph, topo sort
    │   │   │   └── context.py     # build variable context
    │   │   └── excel.py           # import phát sinh
    │   ├── payslip/
    │   └── notification/
    │
    ├── services/                  # cross-module orchestration / facade dùng chung
    │   └── payroll_orchestrator.py
    │
    ├── repositories/              # base repository (generic CRUD) tái dùng
    │   └── base.py
    │
    ├── schemas/                   # schema dùng chung (envelope, error, page)
    │   └── common.py
    │
    ├── models/                    # base model, mixins (timestamp, soft-delete)
    │   └── base.py
    │
    ├── workers/                   # Celery tasks (đăng ký vào celery_app)
    │   ├── attendance_tasks.py    # pull máy chấm công, normalize
    │   ├── payroll_tasks.py       # chunked payroll calc
    │   ├── pdf_tasks.py           # gen + encrypt PDF
    │   └── email_tasks.py         # gửi mail, retry
    │
    ├── cronjobs/                  # định nghĩa schedule cho Celery Beat
    │   └── schedules.py
    │
    ├── middleware/
    │   ├── request_id.py          # gắn X-Request-ID, correlation
    │   ├── audit.py               # bắt mutating request → audit
    │   └── rate_limit.py
    │
    ├── permissions/               # RBAC: catalog permission + checker
    │   ├── catalog.py             # PERMISSIONS = {"employee:read", ...}
    │   └── checker.py             # has_permission(user, perm, resource?)
    │
    ├── audit/                     # audit cross-cutting
    │   ├── recorder.py            # ghi audit_logs (immutable)
    │   └── masking.py             # mask dữ liệu nhạy cảm trong log
    │
    ├── integrations/
    │   ├── timeclock/             # adapter máy chấm công
    │   │   ├── base.py            # interface TimeclockAdapter
    │   │   ├── mdb_adapter.py     # đọc .mdb (MS Access)
    │   │   ├── sqlexpress_adapter.py
    │   │   └── tcp_adapter.py     # kết nối IP trực tiếp (vd ZKTeco)
    │   ├── email/
    │   │   └── smtp_client.py
    │   └── storage/
    │       └── s3_client.py       # MinIO/S3
    │
    └── tests/
        ├── conftest.py            # fixtures: test db, client, factories
        ├── unit/                  # test engine payroll, evaluator...
        ├── integration/           # test repository + DB thật (testcontainers)
        ├── api/                   # test endpoint qua TestClient
        └── factories/             # factory_boy / faker
```

### Vai trò từng thư mục

| Thư mục | Trách nhiệm | Quy tắc |
|---|---|---|
| `core/` | Hạ tầng: config, db, security, redis, events, logging | KHÔNG chứa business logic, không import module |
| `api/` | HTTP layer: nhận request, validate (Pydantic), gọi service, trả response | "Mỏng" — không có logic nghiệp vụ |
| `modules/<x>/` | Bounded context: models + schemas + repository + service | Chỉ giao tiếp module khác qua `service` (facade) |
| `modules/<x>/service.py` | Use-case, transaction boundary, gọi repository + publish event | Nơi đặt business rule |
| `modules/<x>/repository.py` | Truy vấn DB thuần (SQLAlchemy), không logic | Trả model/row, nhận session |
| `services/` | Orchestrate nhiều module (vd payroll cần employee+attendance+approval) | Facade tầng cao |
| `repositories/base.py` | Generic CRUD (get/list/create/update/soft_delete) | Kế thừa lại |
| `workers/` | Celery task (nặng/nền/retry) | Task gọi service, không nhúng logic |
| `cronjobs/` | Khai báo lịch (beat schedule) | Chỉ schedule, logic ở workers |
| `middleware/` | Cross-cutting HTTP: request-id, audit, rate-limit | |
| `permissions/` | Catalog quyền + hàm kiểm tra RBAC | Single source of truth quyền |
| `audit/` | Ghi log bất biến + masking | Dùng bởi middleware & service |
| `integrations/` | Adapter hệ ngoài (máy chấm công, email, storage) | Interface + impl, dễ mock test |
| `tests/` | unit / integration / api | Coverage trọng tâm payroll & attendance |

---

## 2.2. Database Design (PostgreSQL 16)

### 2.2.1. ERD (ASCII, rút gọn quan hệ chính)

```
                    ┌──────────┐        ┌──────────────┐       ┌───────────────┐
                    │  roles   │◄──────►│ role_perms   │◄─────►│  permissions  │
                    └────┬─────┘  M:N   └──────────────┘       └───────────────┘
                         │ M:N (user_roles)
                    ┌────▼─────┐        ┌──────────────────┐
                    │  users   │1──────1│    employees     │
                    └────┬─────┘        └───┬───────┬──────┘
                         │                  │       │
       ┌─────────────────┘                  │       │ 1:N
       │                          ┌─────────▼──┐  ┌─▼────────────────────────┐
       │                          │departments │  │employee_dynamic_profiles │
       │                          └────────────┘  │  (JSONB data)            │
       │                          ┌────────────┐  └──────────────────────────┘
       │   profile_categories 1──N│profile_    │
       │                          │  fields    │
       │                          └────────────┘
       │
  ┌────▼────────────┐   ┌────────────────────┐   ┌─────────────────────┐
  │attendance_raw_  │   │ attendance_daily   │   │ attendance_monthly  │
  │  logs (part.)   │──►│ (1 row/emp/day)    │──►│ (1 row/emp/period)  │
  └─────────────────┘   └────────────────────┘   └─────────────────────┘
                                                            │ feeds
  ┌─────────────────┐   ┌────────────────────┐   ┌─────────▼───────────┐
  │ leave_requests  │──►│ approval_instances │──►│   payroll_runs      │
  │ benefit_requests│   │ approval_steps     │   │   payroll_run_items │
  └─────────────────┘   │ approval_workflows │   └─────────┬───────────┘
                        └────────────────────┘             │ 1:1
  ┌──────────────────┐  ┌───────────────────────────┐  ┌───▼──────┐
  │salary_components │─►│salary_component_assignments│  │ payslips │
  └──────────────────┘  └───────────────────────────┘  └────┬─────┘
                                                            │ N:1
  ┌──────────────┐   ┌───────────────────┐   ┌─────────────▼──────┐
  │ audit_logs   │   │  notifications    │   │  file_attachments  │
  │ (immutable,  │   │                   │   │  (polymorphic ref) │
  │  partitioned)│   └───────────────────┘   └────────────────────┘
  └──────────────┘
```

### 2.2.2. Danh sách bảng theo module

| Module | Bảng |
|---|---|
| **Auth/RBAC** | `users`, `roles`, `permissions`, `role_permissions`, `user_roles`, `refresh_tokens`, `login_attempts` |
| **Org/Employee** | `departments`, `positions`, `employees`, `profile_categories`, `profile_fields`, `employee_dynamic_profiles` |
| **Master config** | `work_shifts`, `holidays`, `system_settings` |
| **Attendance** | `attendance_devices`, `attendance_raw_logs` (partition), `attendance_daily`, `attendance_monthly` |
| **Leave/Approval** | `leave_types`, `leave_requests`, `benefit_requests`, `approval_workflows`, `approval_workflow_steps`, `approval_instances`, `approval_step_instances` |
| **Payroll** | `salary_components`, `salary_component_assignments`, `payroll_periods`, `payroll_formulas`, `payroll_runs`, `payroll_run_items`, `payroll_input_values` |
| **Payslip** | `payslips` |
| **Notification** | `notifications` |
| **Audit** | `audit_logs` (partition) |
| **File** | `file_attachments` |

### 2.2.3. Sample SQL Schema (DDL trọng tâm)

```sql
-- ============ EXTENSIONS ============
CREATE EXTENSION IF NOT EXISTS pgcrypto;     -- gen_random_uuid, crypt (tùy chọn)
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- search ILIKE/fuzzy
CREATE EXTENSION IF NOT EXISTS btree_gin;    -- index JSONB kết hợp

-- ============ RBAC ============
CREATE TABLE roles (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        VARCHAR(50)  UNIQUE NOT NULL,        -- 'ADMIN','HR','MANAGER','EMPLOYEE'
    name        VARCHAR(100) NOT NULL,
    is_system   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE permissions (
    id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code  VARCHAR(100) UNIQUE NOT NULL,              -- 'payroll:read','employee:write'
    name  VARCHAR(150) NOT NULL
);

CREATE TABLE role_permissions (
    role_id       BIGINT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id BIGINT NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE users (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username        VARCHAR(100) UNIQUE NOT NULL,
    email           CITEXT UNIQUE,
    password_hash   TEXT NOT NULL,                    -- Argon2id
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    is_locked       BOOLEAN NOT NULL DEFAULT FALSE,
    failed_attempts SMALLINT NOT NULL DEFAULT 0,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_roles (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id BIGINT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL,                        -- SHA-256 của token, KHÔNG lưu raw
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    user_agent  TEXT,
    ip          INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_refresh_user ON refresh_tokens(user_id) WHERE revoked_at IS NULL;

CREATE TABLE login_attempts (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username   VARCHAR(100),
    ip         INET,
    success    BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_login_ip_time ON login_attempts(ip, created_at DESC);

-- ============ ORG & EMPLOYEE ============
CREATE TABLE departments (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code       VARCHAR(50) UNIQUE NOT NULL,
    name       VARCHAR(150) NOT NULL,
    parent_id  BIGINT REFERENCES departments(id),
    manager_id BIGINT,                                 -- FK employees (set sau)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE positions (
    id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(150) NOT NULL
);

CREATE TABLE employees (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_code   VARCHAR(50) UNIQUE NOT NULL,        -- mã NV
    user_id         BIGINT UNIQUE REFERENCES users(id),
    full_name       VARCHAR(200) NOT NULL,
    department_id   BIGINT REFERENCES departments(id),
    position_id     BIGINT REFERENCES positions(id),
    manager_id      BIGINT REFERENCES employees(id),    -- self-ref: cấp trên trực tiếp
    join_date       DATE,
    status          VARCHAR(20) NOT NULL DEFAULT 'ACTIVE', -- ACTIVE/INACTIVE/TERMINATED
    -- ===== Trường nhạy cảm: lưu mã hóa AES-256 dạng BYTEA =====
    enc_national_id BYTEA,                               -- CCCD
    enc_phone       BYTEA,
    enc_bank_account BYTEA,
    enc_base_salary  BYTEA,                              -- lương cứng
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_emp_dept ON employees(department_id);
CREATE INDEX ix_emp_manager ON employees(manager_id);
CREATE INDEX ix_emp_name_trgm ON employees USING gin (full_name gin_trgm_ops);

-- ===== HỒ SƠ ĐỘNG =====
CREATE TABLE profile_categories (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code      VARCHAR(50) UNIQUE NOT NULL,
    name      VARCHAR(150) NOT NULL,                    -- 'Thông tin gia đình'
    sort_order INT NOT NULL DEFAULT 0
);

CREATE TABLE profile_fields (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_id  BIGINT NOT NULL REFERENCES profile_categories(id),
    field_key    VARCHAR(80) NOT NULL,                  -- 'so_cmnd_vo'
    label        VARCHAR(200) NOT NULL,
    data_type    VARCHAR(20) NOT NULL,                  -- TEXT/NUMBER/DATE/SELECT/BOOLEAN
    options      JSONB,                                  -- cho SELECT: ["A","B"]
    is_required  BOOLEAN NOT NULL DEFAULT FALSE,
    is_encrypted BOOLEAN NOT NULL DEFAULT FALSE,         -- HR tick "mã hóa"
    validation   JSONB,                                  -- {"regex":..,"min":..,"max":..}
    sort_order   INT NOT NULL DEFAULT 0,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (category_id, field_key)
);

CREATE TABLE employee_dynamic_profiles (
    employee_id BIGINT PRIMARY KEY REFERENCES employees(id) ON DELETE CASCADE,
    data        JSONB NOT NULL DEFAULT '{}'::jsonb,      -- {field_key: value | enc-base64}
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_dyn_profile_gin ON employee_dynamic_profiles USING gin (data jsonb_path_ops);

-- ============ MASTER CONFIG ============
CREATE TABLE work_shifts (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code            VARCHAR(50) UNIQUE NOT NULL,
    name            VARCHAR(150) NOT NULL,
    start_time      TIME NOT NULL,                       -- 08:00
    end_time        TIME NOT NULL,                       -- 17:30
    break_minutes   INT NOT NULL DEFAULT 90,
    standard_days   NUMERIC(5,2),                        -- công chuẩn cố định/tháng (nullable -> auto theo lịch)
    late_grace_min  INT NOT NULL DEFAULT 0,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE holidays (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    holiday_date DATE NOT NULL,
    name        VARCHAR(150) NOT NULL,
    is_paid     BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (holiday_date)
);

CREATE TABLE system_settings (
    key   VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ ATTENDANCE ============
CREATE TABLE attendance_devices (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        VARCHAR(50) UNIQUE NOT NULL,
    name        VARCHAR(150),
    adapter_type VARCHAR(30) NOT NULL,                   -- MDB/SQLEXPRESS/TCP
    config      JSONB NOT NULL,                          -- {host, path, port, dsn...}
    is_active   BOOLEAN NOT NULL DEFAULT TRUE
);

-- Partition theo tháng (RANGE) vì tăng trưởng rất nhanh
CREATE TABLE attendance_raw_logs (
    id          BIGINT GENERATED ALWAYS AS IDENTITY,
    device_id   BIGINT NOT NULL REFERENCES attendance_devices(id),
    employee_code VARCHAR(50),                            -- map sau (NV chưa match)
    employee_id BIGINT REFERENCES employees(id),
    punch_at    TIMESTAMPTZ NOT NULL,
    raw_payload JSONB,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, punch_at)
) PARTITION BY RANGE (punch_at);
-- idempotent: chống trùng cùng 1 lần quét
CREATE UNIQUE INDEX uq_raw_punch ON attendance_raw_logs(device_id, employee_code, punch_at);
-- ví dụ partition tháng:
CREATE TABLE attendance_raw_logs_2026_05 PARTITION OF attendance_raw_logs
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');

CREATE TABLE attendance_daily (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id   BIGINT NOT NULL REFERENCES employees(id),
    work_date     DATE NOT NULL,
    shift_id      BIGINT REFERENCES work_shifts(id),
    first_in      TIMESTAMPTZ,
    last_out      TIMESTAMPTZ,
    late_minutes  INT NOT NULL DEFAULT 0,
    early_minutes INT NOT NULL DEFAULT 0,
    ot_minutes    INT NOT NULL DEFAULT 0,
    work_value    NUMERIC(4,2) NOT NULL DEFAULT 0,        -- công quy đổi: 0 / 0.5 / 1
    status        VARCHAR(20) NOT NULL DEFAULT 'NORMAL',  -- NORMAL/MISSING/LEAVE/HOLIDAY
    source        VARCHAR(20) NOT NULL DEFAULT 'DEVICE',  -- DEVICE/MANUAL/LEAVE
    note          TEXT,
    UNIQUE (employee_id, work_date)                       -- idempotent recompute
);
CREATE INDEX ix_daily_emp_date ON attendance_daily(employee_id, work_date);

CREATE TABLE attendance_monthly (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id   BIGINT NOT NULL REFERENCES employees(id),
    period        CHAR(7) NOT NULL,                       -- '2026-05'
    standard_days NUMERIC(5,2) NOT NULL,
    actual_days   NUMERIC(5,2) NOT NULL DEFAULT 0,
    leave_days    NUMERIC(5,2) NOT NULL DEFAULT 0,
    paid_leave_days NUMERIC(5,2) NOT NULL DEFAULT 0,
    ot_hours      NUMERIC(6,2) NOT NULL DEFAULT 0,
    late_count    INT NOT NULL DEFAULT 0,
    detail        JSONB,                                   -- breakdown
    locked        BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (employee_id, period)
);

-- ============ APPROVAL & LEAVE ============
CREATE TABLE leave_types (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code      VARCHAR(50) UNIQUE NOT NULL,                -- ANNUAL, MATERNITY...
    name      VARCHAR(150) NOT NULL,
    is_paid   BOOLEAN NOT NULL DEFAULT TRUE,
    affects_payroll JSONB                                  -- {set_company_salary:0, bhxh_tag:true}
);

CREATE TABLE approval_workflows (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code      VARCHAR(50) UNIQUE NOT NULL,
    name      VARCHAR(150) NOT NULL,
    target_type VARCHAR(40) NOT NULL,                      -- LEAVE / BENEFIT / PAYROLL
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE approval_workflow_steps (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workflow_id BIGINT NOT NULL REFERENCES approval_workflows(id) ON DELETE CASCADE,
    step_order  INT NOT NULL,
    approver_type VARCHAR(30) NOT NULL,                    -- MANAGER / ROLE / SPECIFIC_USER
    approver_ref  VARCHAR(100),                            -- role_code / user_id
    sla_hours   INT,                                       -- escalation sau X giờ
    UNIQUE (workflow_id, step_order)
);

CREATE TABLE leave_requests (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id  BIGINT NOT NULL REFERENCES employees(id),
    leave_type_id BIGINT NOT NULL REFERENCES leave_types(id),
    start_date   DATE NOT NULL,
    end_date     DATE NOT NULL,
    total_days   NUMERIC(5,2) NOT NULL,
    reason       TEXT,
    status       VARCHAR(20) NOT NULL DEFAULT 'PENDING',   -- PENDING/APPROVED/REJECTED/CANCELLED
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE benefit_requests (                            -- chế độ nâng cao: thai sản...
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id  BIGINT NOT NULL REFERENCES employees(id),
    benefit_code VARCHAR(50) NOT NULL,                     -- MATERNITY, WORK_INJURY...
    start_date   DATE NOT NULL,
    end_date     DATE,
    payload      JSONB,
    status       VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Instance khi 1 đơn đi vào workflow
CREATE TABLE approval_instances (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workflow_id   BIGINT NOT NULL REFERENCES approval_workflows(id),
    target_type   VARCHAR(40) NOT NULL,                    -- LEAVE/BENEFIT
    target_id     BIGINT NOT NULL,                         -- id của leave_requests/benefit_requests
    current_step  INT NOT NULL DEFAULT 1,
    status        VARCHAR(20) NOT NULL DEFAULT 'IN_PROGRESS', -- IN_PROGRESS/APPROVED/REJECTED/CANCELLED
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ
);
CREATE INDEX ix_appr_target ON approval_instances(target_type, target_id);

CREATE TABLE approval_step_instances (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instance_id   BIGINT NOT NULL REFERENCES approval_instances(id) ON DELETE CASCADE,
    step_order    INT NOT NULL,
    approver_user_id BIGINT REFERENCES users(id),
    action        VARCHAR(20),                              -- APPROVE/REJECT/null(pending)
    comment       TEXT,
    acted_at      TIMESTAMPTZ,
    due_at        TIMESTAMPTZ                                -- cho escalation
);

-- ============ PAYROLL ============
CREATE TABLE salary_components (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    var_code    VARCHAR(60) UNIQUE NOT NULL,               -- 'thuong_nong' (biến trong công thức)
    name        VARCHAR(150) NOT NULL,
    kind        VARCHAR(10) NOT NULL,                       -- EARNING / DEDUCTION
    value_type  VARCHAR(15) NOT NULL DEFAULT 'INPUT',       -- INPUT(import Excel)/FIXED/FORMULA
    default_value NUMERIC(18,2) NOT NULL DEFAULT 0,
    is_sensitive BOOLEAN NOT NULL DEFAULT TRUE,             -- ẩn/mã hóa
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE salary_component_assignments (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    component_id  BIGINT NOT NULL REFERENCES salary_components(id) ON DELETE CASCADE,
    scope         VARCHAR(15) NOT NULL,                     -- ALL/DEPARTMENT/POSITION/EMPLOYEE
    scope_ref_id  BIGINT,                                   -- dept/pos/emp id (null nếu ALL)
    effective_from DATE NOT NULL,
    effective_to   DATE
);
CREATE INDEX ix_sca_scope ON salary_component_assignments(scope, scope_ref_id);

CREATE TABLE payroll_periods (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period    CHAR(7) UNIQUE NOT NULL,                      -- '2026-05'
    status    VARCHAR(15) NOT NULL DEFAULT 'OPEN',          -- OPEN/CALCULATING/LOCKED/CLOSED
    locked_at TIMESTAMPTZ
);

CREATE TABLE payroll_formulas (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period      CHAR(7) NOT NULL,
    target_var  VARCHAR(60) NOT NULL,                       -- 'TONG_LUONG'
    expression  TEXT NOT NULL,                              -- '(luong_cung/cong_chuan*cong_thuc_te)+...'
    eval_order  INT,                                        -- topo order (tự tính)
    created_by  BIGINT REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (period, target_var)
);

CREATE TABLE payroll_runs (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period      CHAR(7) NOT NULL,
    status      VARCHAR(15) NOT NULL DEFAULT 'DRAFT',        -- DRAFT/LOCKED/CONFIRMED/CANCELLED
    formula_snapshot JSONB,                                  -- đóng băng công thức lúc chốt
    created_by  BIGINT REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at   TIMESTAMPTZ
);

CREATE TABLE payroll_run_items (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id        BIGINT NOT NULL REFERENCES payroll_runs(id) ON DELETE CASCADE,
    employee_id   BIGINT NOT NULL REFERENCES employees(id),
    input_snapshot JSONB NOT NULL,                           -- mọi biến đầu vào (reproducible)
    result        JSONB NOT NULL,                            -- {var: value} kết quả từng biến
    net_amount    BYTEA,                                     -- tổng thực nhận (mã hóa)
    status        VARCHAR(20) NOT NULL DEFAULT 'CALCULATED', -- CALCULATED/CONFIRMED/REJECTED
    employee_feedback TEXT,
    UNIQUE (run_id, employee_id)
);

CREATE TABLE payroll_input_values (                          -- số liệu import Excel
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period       CHAR(7) NOT NULL,
    employee_id  BIGINT NOT NULL REFERENCES employees(id),
    component_id BIGINT NOT NULL REFERENCES salary_components(id),
    value        NUMERIC(18,2) NOT NULL DEFAULT 0,
    UNIQUE (period, employee_id, component_id)
);

-- ============ PAYSLIP ============
CREATE TABLE payslips (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_item_id   BIGINT NOT NULL UNIQUE REFERENCES payroll_run_items(id),
    employee_id   BIGINT NOT NULL REFERENCES employees(id),
    period        CHAR(7) NOT NULL,
    file_id       BIGINT,                                    -- FK file_attachments (PDF)
    pdf_password_hint VARCHAR(50),                            -- 'CCCD 6 số cuối'
    email_status  VARCHAR(15) NOT NULL DEFAULT 'PENDING',    -- PENDING/SENT/FAILED
    sent_at       TIMESTAMPTZ,
    retry_count   INT NOT NULL DEFAULT 0
);

-- ============ NOTIFICATION ============
CREATE TABLE notifications (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id),
    type        VARCHAR(50) NOT NULL,
    title       VARCHAR(200) NOT NULL,
    body        TEXT,
    payload     JSONB,
    is_read     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_notif_user_unread ON notifications(user_id) WHERE is_read = FALSE;

-- ============ FILE ATTACHMENTS (polymorphic) ============
CREATE TABLE file_attachments (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    owner_type   VARCHAR(40) NOT NULL,                       -- BENEFIT_REQUEST/PAYSLIP/EMPLOYEE
    owner_id     BIGINT NOT NULL,
    storage_key  TEXT NOT NULL,                              -- key trên S3/MinIO
    filename     VARCHAR(255) NOT NULL,
    content_type VARCHAR(100),
    size_bytes   BIGINT,
    is_encrypted BOOLEAN NOT NULL DEFAULT FALSE,
    uploaded_by  BIGINT REFERENCES users(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_file_owner ON file_attachments(owner_type, owner_id);

-- ============ AUDIT LOGS (immutable, partitioned) ============
CREATE TABLE audit_logs (
    id          BIGINT GENERATED ALWAYS AS IDENTITY,
    actor_id    BIGINT,                                      -- user thực hiện
    action      VARCHAR(20) NOT NULL,                        -- CREATE/UPDATE/DELETE/VIEW_SENSITIVE
    entity      VARCHAR(60) NOT NULL,                        -- 'payroll_run_items'
    entity_id   VARCHAR(60),
    old_value   JSONB,                                       -- đã mask dữ liệu nhạy cảm
    new_value   JSONB,
    ip          INET,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE TABLE audit_logs_2026_05 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE INDEX ix_audit_entity ON audit_logs(entity, entity_id, created_at DESC);
```

### 2.2.4. Index strategy

| Loại | Áp dụng | Lý do |
|---|---|---|
| B-tree composite | `(employee_id, work_date)`, `(employee_id, period)` | Truy vấn chấm công/lương theo NV + thời gian |
| GIN `jsonb_path_ops` | `employee_dynamic_profiles.data`, `audit_logs.new_value` | Search trong JSONB (`@>`, `?`) |
| GIN `pg_trgm` | `employees.full_name` | Search tên ILIKE / fuzzy |
| Partial index | `refresh_tokens WHERE revoked_at IS NULL`, `notifications WHERE is_read=FALSE` | Nhỏ gọn, query phổ biến |
| Unique natural key | `(device_id, employee_code, punch_at)`, `(employee_id, work_date)` | Idempotent batch, chống trùng |

### 2.2.5. Partition strategy

- **`attendance_raw_logs`** & **`audit_logs`**: RANGE theo tháng. Tăng trưởng tuyến tính theo NV×ngày. Lợi: drop partition cũ nhanh (archive), query tháng chỉ scan 1 partition.
- Tự động tạo partition tháng kế tiếp bằng cron (`pg_partman` hoặc task Celery beat tạo `CREATE TABLE ... PARTITION OF`).
- `notifications` cân nhắc partition khi >50M rows.

### 2.2.6. JSONB usage (khi nào dùng / không dùng)

| Dùng JSONB | KHÔNG dùng JSONB |
|---|---|
| Hồ sơ động (`employee_dynamic_profiles.data`) — schema thay đổi runtime | Dữ liệu quan hệ rõ ràng (employee, department) |
| `audit_logs.old/new_value` — cấu trúc thay đổi theo entity | Số tiền cần tính toán/aggregate thường xuyên |
| `payroll_run_items.input_snapshot/result` — reproducibility | Foreign key references |
| `config`, `options`, `validation`, `payload` | |

> Nguyên tắc: JSONB cho **schema-less / snapshot / config**. Dữ liệu cần JOIN/aggregate/constraint → cột quan hệ.

### 2.2.7. Encryption fields

- Cột `enc_*` kiểu **BYTEA**, lưu ciphertext AES-256-GCM (nonce + tag prepend). Chi tiết ở [Phần 2B §2.3](02b-backend-security-api.md).
- Field động `is_encrypted=TRUE` → value trong JSONB lưu base64 ciphertext, có prefix `enc:` để phân biệt.

### 2.2.8. Audit strategy (DB-level protection)

- `audit_logs` chỉ INSERT. Tạo **role DB riêng** cho app (`hrm_app`) với GRANT chỉ `SELECT, INSERT` trên `audit_logs` — **REVOKE UPDATE, DELETE** (kể cả superuser app role).
- Thêm rule chặn cứng:

```sql
CREATE RULE audit_no_update AS ON UPDATE TO audit_logs DO INSTEAD NOTHING;
CREATE RULE audit_no_delete AS ON DELETE TO audit_logs DO INSTEAD NOTHING;
```

- Quản trị DB thực sự (xóa partition cũ để archive) dùng role tách biệt, có quy trình + audit ngoài hệ thống.

→ Tiếp: [Phần 2B — Security & API Design](02b-backend-security-api.md).
