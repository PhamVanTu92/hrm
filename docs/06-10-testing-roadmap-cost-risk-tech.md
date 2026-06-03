# PHẦN 6–10 — TESTING, ROADMAP, NHÂN SỰ/CHI PHÍ, RỦI RO, CÔNG NGHỆ

---

# PHẦN 6 — TESTING STRATEGY

## 6.1. Pytest structure

```
tests/
├── conftest.py            # fixtures: event_loop, test_db (testcontainers), async_client, factories
├── unit/                  # KHÔNG chạm DB — logic thuần
│   ├── test_payroll_evaluator.py   # SimpleEval, công thức, an toàn
│   ├── test_dependency_graph.py    # topo sort, phát hiện circular
│   ├── test_attendance_calc.py     # late/early/OT/work_value
│   └── test_encryption.py          # AES encrypt/decrypt round-trip
├── integration/           # repository + DB thật
│   ├── test_employee_repo.py
│   └── test_payroll_run.py
├── api/                   # endpoint qua httpx AsyncClient
│   ├── test_auth.py
│   ├── test_payroll_api.py
│   └── test_rbac.py       # 403 khi thiếu quyền
└── factories/             # factory_boy
```

## 6.2. Test pyramid & trọng tâm

| Loại | Tỷ lệ | Trọng tâm HRM |
|---|---|---|
| Unit | ~60% | **Payroll engine, attendance calc, encryption** (rủi ro cao nhất) |
| Integration | ~25% | Repository, transaction, idempotent UPSERT, lock |
| API | ~15% | Auth flow, RBAC 403, envelope, pagination |
| Security/E2E | bổ sung | bruteforce lock, audit immutable, PDF password |

## 6.3. Mocking strategy
- **Mock ở ranh giới ngoài**: máy chấm công (adapter), SMTP, S3 → fake/in-memory.
- **KHÔNG mock DB** cho integration/payroll — dùng **testcontainers Postgres** thật (payroll/attendance phụ thuộc hành vi SQL: JSONB, ON CONFLICT, partition). Mock DB dễ cho pass giả.
- Celery: `task_always_eager=True` trong test → chạy đồng bộ.

## 6.4. Seed database strategy
- `factories/` (factory_boy + Faker) tạo employee, salary_component, attendance.
- `scripts/seed.py`: roles/permissions/master data chuẩn (dev + e2e).
- Mỗi test transaction rollback (fixture `db` mở transaction, rollback cuối test) → cô lập.

## 6.5. Payroll accuracy test (bắt buộc)

```python
def test_payroll_formula_accuracy():
    ctx = {"luong_cung": 20_000_000, "cong_chuan": 26, "cong_thuc_te": 24,
           "phu_cap_an_trua": 730_000, "thuong_nong": 1_000_000}
    formulas = [Formula("LUONG_NGAY", "luong_cung/cong_chuan"),
                Formula("LUONG_CONG", "LUONG_NGAY*cong_thuc_te"),
                Formula("TONG_LUONG", "LUONG_CONG+phu_cap_an_trua+thuong_nong")]
    order = build_eval_order(formulas, set(ctx))
    res = calculate(ctx, formulas, order)
    assert res["TONG_LUONG"] == pytest.approx(20_000_000/26*24 + 730_000 + 1_000_000)

def test_circular_formula_rejected():
    with pytest.raises(DomainError, match="vòng"):
        build_eval_order([Formula("A","B+1"), Formula("B","A+1")], set())

def test_coalesce_missing_component():
    # NV không có thuong_nong → coalesce 0, không lỗi
    ...

def test_snapshot_reproducibility():
    # đổi công thức/lương sau khi lock → tái tính từ snapshot vẫn ra số cũ
    ...
```

## 6.6. Attendance & security test
- Attendance: re-run normalize cùng ngày → không nhân đôi (idempotent); late/early/OT đúng biên; holiday/leave bù công.
- Security: 5 lần sai pass → khóa; access token hết hạn → 401→refresh; thiếu perm → 403; audit_logs UPDATE/DELETE bị chặn; PDF mở đúng pass = 6 số cuối CCCD.

---

# PHẦN 7 — ROADMAP TRIỂN KHAI

> Tài liệu gốc đề xuất 10 tuần. Dưới đây ánh xạ thành phase + cảnh báo rủi ro timeline.

## Phase 1 — Foundation & Security (Tuần 1–2) → nền MVP
| Hạng mục | Ưu tiên kỹ thuật | Rủi ro | Phụ thuộc |
|---|---|---|---|
| Schema DB + Alembic + partition | Cao | Sai thiết kế JSONB/encrypt → đắt sửa | — |
| AES-256 module + key mgmt | Cao | Mất key = mất data | Schema |
| Auth (JWT+refresh+Argon2) + RBAC | Cao | Lỗ hổng = toàn hệ thống | Schema |
| Audit logs + DB immutable | Cao | — | Schema |

## Phase 2 — Core HR & Attendance (Tuần 3–5)
| Hạng mục | Ưu tiên | Rủi ro | Phụ thuộc |
|---|---|---|---|
| Employee + Dynamic Profile (JSONB) | Cao | Validate động phức tạp | Auth |
| Master config (ca, lễ) | Trung | — | — |
| **Attendance cron + adapter máy chấm công** | Cao | **Tích hợp .mdb/SQL Express khó đoán** | Master |
| Đơn từ + Approval workflow đa cấp | Cao | State machine race condition | Employee |

## Phase 3 — Payroll & Automation (Tuần 6–8) → **rủi ro cao nhất**
| Hạng mục | Ưu tiên | Rủi ro | Phụ thuộc |
|---|---|---|---|
| **Dynamic Payroll Engine** (parser, graph, snapshot) | Tối cao | Sai số lương = mất niềm tin | Attendance, Components |
| Excel import phát sinh | Cao | Dữ liệu bẩn | Engine |
| Payslip PDF + encrypt + email queue | Cao | Gửi nhầm/lộ phiếu | Payroll lock |

## MVP (cuối Tuần 8)
Auth/RBAC + Employee động + Attendance tự động + Approval + Payroll tính được + Payslip gửi mail. Đủ chạy 1 phòng ban thử nghiệm.

## Phase 4 / Production (Tuần 9–10)
| Hạng mục | Nội dung |
|---|---|
| Hardening | Security test tầng DB, pentest cơ bản, rate-limit |
| Parallel run | Chạy song song hệ cũ trên 1 phòng mẫu, đối soát sai số lương |
| Observability | Monitoring, backup tự động, alert |
| Go-live | Toàn công ty |

> **Cảnh báo thực tế:** 10 tuần khả thi cho ~100–300 NV với team đủ mạnh, **nhưng** Payroll Engine + tích hợp máy chấm công thường vượt ước tính. Khuyến nghị đệm thêm 2–3 tuần buffer hoặc giảm scope MVP (vd Excel import thủ công trước, tích hợp máy chấm công sau).

---

# PHẦN 8 — ƯỚC TÍNH NHÂN SỰ & CHI PHÍ

## 8.1. Đội ngũ theo giai đoạn

| Vai trò | MVP (T1–8) | Production-ready (T9–14) | Enterprise (10k NV) |
|---|---|---|---|
| Backend (FastAPI) | 2 (1 senior payroll) | 2–3 | 3–4 |
| Frontend (Next.js) | 1–2 | 2 | 2–3 |
| QA | 0.5 (BE kiêm) → 1 | 1 | 2 (1 automation) |
| DevOps | 0.5 (part-time) | 1 | 1–2 |
| BA/PO | 1 | 1 | 1–2 |
| **Tổng (FTE)** | **~5–6** | **~7–8** | **~10–13** |

## 8.2. Ghi chú phân bổ
- **Senior backend** phải "gánh" Payroll Engine + attendance pipeline (2 module rủi ro nhất) — đừng giao junior.
- BA quan trọng giai đoạn đầu: chuẩn hóa quy tắc lương/công, ngày lễ, chế độ BHXH (sai nghiệp vụ = code đúng vẫn sai).
- QA tham gia từ Phase 2 để xây bộ test payroll accuracy.
- DevOps part-time ở MVP (Docker Compose 1 VPS), full-time khi scale (replica, monitoring).

## 8.3. Hạ tầng (ước tính/tháng, tham khảo)
| Quy mô | Hạ tầng | Chi phí tương đối |
|---|---|---|
| 100–300 NV | 1 VPS 4vCPU/8GB + backup S3 | Thấp |
| 1k–5k NV | App 2–3 node + DB primary/replica + Redis + MinIO | Trung |
| 10k NV | Cluster app, DB lớn + replica, worker farm, monitoring stack | Cao |

---

# PHẦN 9 — RỦI RO KỸ THUẬT & MITIGATION

| Nhóm | Rủi ro | Tác động | Mitigation |
|---|---|---|---|
| **Security** | Rò rỉ AES key | Lộ toàn bộ lương/CCCD | Key qua Vault/secret, không trong image; rotation + key_version; phân quyền truy cập key |
| Security | JWT secret yếu/lộ | Giả mạo token | Secret ≥32B random; HS256→RS256 nếu nhiều service; access TTL ngắn |
| Security | Bruteforce login | Chiếm tài khoản | Lock 5 lần, rate-limit IP, audit, CAPTCHA |
| Security | SQL injection / mass assign | Lộ/hỏng data | ORM param hóa, Pydantic strict, không raw SQL nối chuỗi |
| **Payroll** | Sai công thức/circular | Trả lương sai | DAG validate khi lưu, payroll accuracy test, parallel-run đối soát |
| Payroll | `eval` không an toàn | RCE | **Chỉ SimpleEval** whitelist; cấm attribute/import |
| Payroll | Sửa data sau khi chốt | Mất tính kiểm toán | Snapshot bất biến, lock period, adjustment run thay vì sửa |
| Payroll | Float sai số tiền | Lệch tiền | Dùng `Decimal`/NUMERIC, round nhất quán 2 chữ số |
| **Attendance** | Tích hợp máy chấm công lỗi/thiếu log | Thiếu công | Adapter retry, reconciliation report, cho phép sửa tay (audit) |
| Attendance | Lệch timezone | Sai giờ vào/ra | TIMESTAMPTZ, chuẩn hóa Asia/Ho_Chi_Minh |
| Attendance | Cron chạy trùng/skip | Nhân đôi/thiếu | Idempotent UPSERT, RedBeat lock |
| **Data corruption** | Migration hỏng | Mất/hỏng data | Migration backward-compat, backup trước migrate, test trên staging |
| Data corruption | Mất backup/không restore được | Thảm họa | 3-2-1, backup mã hóa, **test restore hàng tháng**, PITR |
| **Concurrency** | 2 HR chốt lương cùng lúc | Double run | UNIQUE partial index 1 run active/period, `SELECT FOR UPDATE` |
| Concurrency | Duyệt đơn đồng thời | State sai | Row lock instance, kiểm transition hợp lệ |
| Concurrency | Race normalize attendance | Sai công | Natural key UPSDERT, lock guard `locked` |

---

# PHẦN 10 — ĐỀ XUẤT CÔNG NGHỆ CỤ THỂ

| Hạng mục | Lựa chọn | Lý do kỹ thuật | Thay thế đã cân nhắc |
|---|---|---|---|
| Web framework | **FastAPI** | Async, Pydantic validate, OpenAPI tự sinh, hiệu năng | Django (nặng), Flask (thiếu async/validate) |
| Python | **3.12** | Hiệu năng, type hints tốt | 3.11 |
| ORM | **SQLAlchemy 2.0 (async)** | Mạnh nhất, async, type-safe, hỗ trợ JSONB/partition | Tortoise (yếu hơn), SQLModel (thin wrapper) |
| Migration | **Alembic** | Chuẩn của SQLAlchemy, autogenerate | — |
| DB | **PostgreSQL 16** | JSONB, partition, RLS, mạnh & toàn vẹn | MySQL (JSON yếu hơn) |
| PG extensions | `pgcrypto`, `pg_trgm`, `btree_gin` (tùy: `pg_partman`) | UUID, fuzzy search, index JSONB, auto-partition | — |
| Driver | **asyncpg** (+`psycopg` cho tool) | Nhanh nhất async | psycopg3 async |
| Pool | **PgBouncer** | Pool connection ở mức transaction | SQLAlchemy pool (đủ nhỏ) |
| Cache | **Redis 7** | Cache + broker + rate-limit + lock | Memcached (ít tính năng) |
| Queue/Task | **Celery** (+ RedBeat) | Trưởng thành, retry/backoff, chord, beat | RQ (đơn giản, ít tính năng), Dramatiq, ARQ (async-native, nhẹ hơn nếu thuần async) |
| Password hash | **argon2-cffi (Argon2id)** | Kháng GPU tốt nhất | bcrypt (passlib) |
| JWT | **pyjwt** | Nhẹ, ít CVE | python-jose |
| Crypto | **cryptography (AESGCM)** | AEAD, chuẩn | PyNaCl |
| Formula eval | **simpleeval** | Sandbox an toàn cho công thức lương | asteval (rộng hơn, kém an toàn), eval (cấm) |
| Dep graph | **networkx** | Topo sort, phát hiện cycle | tự viết (tốn công) |
| Excel | **openpyxl** | Đọc/ghi .xlsx, streaming read_only | pandas (nặng), xlsxwriter (chỉ ghi) |
| PDF | **WeasyPrint** + **pikepdf** | HTML→PDF Unicode tốt + mã hóa AES PDF | ReportLab (thủ công), PyPDF2 (thiếu mã hóa mạnh) |
| Máy chấm công | **pyodbc** (.mdb/SQL Express) / **pyzk** (ZKTeco TCP) | Đọc nguồn phổ biến tại VN | mdbtools (CLI) |
| Email | `aiosmtplib` / SMTP qua Celery | Async gửi mail | SES SDK nếu dùng AWS |
| Storage | **MinIO** (S3 API) | Self-host, tương thích S3 | S3/Spaces (cloud) |
| Rate limit | **slowapi** | Tích hợp FastAPI, backend Redis | nginx limit_req (lớp ngoài) |
| Logging | **structlog** | JSON log, correlation | loguru |
| Monitoring | Prometheus + Grafana + Sentry + Flower | Chuẩn, mở | Datadog (trả phí) |
| Validation | **Pydantic v2** | Nhanh, type-safe | — |
| Settings | **pydantic-settings** | Env validate | — |
| Test | **pytest** + httpx + testcontainers + factory_boy | Async test, DB thật | unittest |
| Lint/format | **ruff** + **mypy** | Nhanh, all-in-one | flake8+black+isort |
| Package mgr | **uv** (hoặc poetry) | Nhanh, lock reproducible | pip-tools |
| Frontend | **Next.js + TS** | Hệ sinh thái, RBAC routing | Vue/Nuxt, React+Vite |
| FE data | TanStack Query/Table + RHF+Zod + Zustand + shadcn/ui | Form/table động, cache | Redux (nặng) |

---

## Checklist "bắt đầu coding ngay"
- [ ] Tạo repo, cấu trúc thư mục theo [Phần 2A §2.1](02a-backend-folder-database.md)
- [ ] Dựng `docker-compose` (db, redis, minio) + `.env.example`
- [ ] Alembic init + migration đầu (schema [Phần 2A §2.2.3](02a-backend-folder-database.md))
- [ ] `core/security.py` (AES, Argon2, JWT) + test round-trip
- [ ] Auth + RBAC + audit middleware (Phase 1)
- [ ] Seed roles/permissions/master data
- [ ] CI: ruff+mypy+pytest, coverage ≥75% (trọng tâm payroll)

→ Quay lại [README index](README.md).
