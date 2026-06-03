# KẾ HOẠCH TRIỂN KHAI HỆ THỐNG HRM (Production-Ready)

> **Stack:** FastAPI (Python 3.12) + PostgreSQL 16 + Redis 7 + Celery + Next.js
> **Kiến trúc:** Modular Monolith + Clean/Layered + DDD tactical
> **Đối tượng:** Dev team có thể bắt đầu coding ngay sau khi đọc.

Tài liệu này phân tích tài liệu thiết kế HRM v2.0 (in-house) và xây dựng kế hoạch triển khai đầy đủ 11 phần.

## Mục lục

| # | Tài liệu | Nội dung |
|---|---|---|
| 1 | [Tổng quan kiến trúc](01-kien-truc-tong-quan.md) | Mô hình kiến trúc, sơ đồ, luồng dữ liệu, communication, scale 100→10k NV |
| 2A | [Backend: Folder & Database](02a-backend-folder-database.md) | Cấu trúc thư mục, ERD, full SQL schema, index/partition/JSONB/encryption/audit strategy |
| 2B | [Backend: Security & API](02b-backend-security-api.md) | JWT/refresh, RBAC, AES-256, anti-bruteforce, rate-limit, REST API design |
| 3A | [Module: Employee & Attendance](03a-module-employee-attendance.md) | Hồ sơ động JSONB, pipeline chấm công, cron, shift/OT calc, aggregation |
| 3B | [Module: Approval & Payroll](03b-module-approval-payroll.md) | Workflow state machine, **Dynamic Payroll Engine**, dependency graph, snapshot |
| 3C | [Module: Payslip & Audit](03c-module-payslip-audit.md) | PDF + encrypt + email queue, audit immutable, masking |
| 4 | [Frontend](04-frontend.md) | Next.js, dynamic form, RBAC UI, table, auth handling |
| 5 | [DevOps & Deployment](05-devops.md) | Docker, Nginx/SSL, CI/CD, backup, monitoring, scaling |
| 6-10 | [Testing/Roadmap/Cost/Risk/Tech](06-10-testing-roadmap-cost-risk-tech.md) | Test strategy, roadmap 10 tuần, nhân sự/chi phí, rủi ro, đề xuất công nghệ |

## Quyết định kiến trúc cốt lõi
1. **Modular Monolith** — payroll cần transaction nhất quán xuyên module; team nhỏ; timeline 10 tuần.
2. **Async FastAPI** cho I/O, **Celery** cho batch nặng (payroll, PDF, chấm công).
3. **PostgreSQL primary + read replica**, partition `attendance_raw_logs` & `audit_logs`.
4. **AES-256-GCM** tầng app cho dữ liệu nhạy cảm; **Argon2id** cho password.
5. **Payroll reproducible** từ snapshot bất biến; formula eval bằng **SimpleEval** (sandbox).
6. **Audit immutable** — DB rule chặn UPDATE/DELETE.

## Hai module rủi ro cao nhất (đầu tư senior)
- **Dynamic Payroll Engine** ([3B](03b-module-approval-payroll.md)) — formula engine, DAG, snapshot, rollback.
- **Attendance pipeline** ([3A](03a-module-employee-attendance.md)) — tích hợp máy chấm công, idempotent batch.
