# PHẦN 3C — MODULE: PAYSLIP AUTOMATION & AUDIT LOGGING

---

## 3.5. Payslip Automation

### Flow chi tiết

```
HR lock payroll run
   │
   ▼
status=LOCKED → notify từng NV "Bảng lương chờ xác nhận" (in-app + email)
   │
   ▼
NV xem chi tiết (/payslips/me)
   ├── đúng → POST /confirm  ──► run_item.status=CONFIRMED
   │                              │
   │                              ▼ publish PayrollConfirmed(run_item_id)
   │                         ┌──────────────────────────────────────────┐
   │                         │ Celery chain (queue: pdf → email):        │
   │                         │  1. gen_payslip_pdf(run_item_id)          │
   │                         │     - render template → PDF               │
   │                         │     - giải mã số liệu (trong worker, quyền)│
   │                         │  2. encrypt_pdf(file, pass=6 số cuối CCCD) │
   │                         │  3. upload S3/MinIO → file_attachments    │
   │                         │  4. send_payslip_email(payslip_id)        │
   │                         │     - đính kèm PDF, retry nếu fail        │
   │                         └──────────────────────────────────────────┘
   │
   └── sai → POST /feedback {lý do} → run_item.status=REJECTED
                                      notify HR sửa → recalc (nếu DRAFT) / adjustment
```

### Queue architecture

```
Redis broker
   ├── queue: pdf      (CPU-bound, concurrency thấp: 2-4 worker)
   ├── queue: email    (I/O-bound, concurrency cao: 8-16, rate-limit SMTP)
   └── queue: default

Celery chain đảm bảo thứ tự: PDF xong mới gửi email.
```

### Async processing & PDF generation

```python
# workers/pdf_tasks.py
@celery.task(bind=True, max_retries=3, default_retry_delay=60, queue="pdf")
def gen_payslip_pdf(self, run_item_id):
    item = load_run_item(run_item_id)              # result JSONB (đã có sẵn số)
    emp  = load_employee(item.employee_id)
    html = render_template("payslip.html", item=item, emp=emp)  # Jinja2
    pdf_bytes = weasyprint_render(html)            # WeasyPrint: HTML→PDF, hỗ trợ tiếng Việt
    cccd = decrypt(emp.enc_national_id)
    password = cccd[-6:]                            # 6 số cuối CCCD
    enc_pdf = encrypt_pdf(pdf_bytes, password)      # pikepdf: AES-256 owner/user pass
    key = f"payslips/{item.period}/{emp.employee_code}.pdf"
    s3_put(key, enc_pdf, content_type="application/pdf")
    file_id = save_file_attachment("PAYSLIP", item.id, key, encrypted=True)
    upsert_payslip(item.id, file_id, pwd_hint="6 số cuối CCCD")
    send_payslip_email.delay(payslip_id_of(item.id))
```

| Nhu cầu | Lib | Lý do |
|---|---|---|
| HTML→PDF | **WeasyPrint** | CSS tốt, Unicode/tiếng Việt chuẩn, template Jinja2 |
| (thay thế) | ReportLab | Kiểm soát thấp, nhưng code thủ công nhiều |
| Khóa pass PDF | **pikepdf** (libqpdf) | Mã hóa AES-256, set user/owner password |
| Template | Jinja2 | Quen thuộc, tách layout |

### Retry & notification

```python
# workers/email_tasks.py
@celery.task(bind=True, max_retries=5, queue="email",
             retry_backoff=True, retry_backoff_max=600, retry_jitter=True)
def send_payslip_email(self, payslip_id):
    ps = load_payslip(payslip_id)
    try:
        pdf = s3_get(ps.file_key)
        smtp_send(to=email_of(ps.employee_id),
                  subject=f"Phiếu lương {ps.period}",
                  body="Mật khẩu mở file: 6 số cuối CCCD của bạn.",
                  attachments=[(f"payslip_{ps.period}.pdf", pdf)])
        mark_sent(payslip_id)
        notify_inapp(ps.employee_id, "Phiếu lương đã gửi tới email của bạn")
    except SMTPException as e:
        mark_retry(payslip_id)                      # retry_count++
        raise self.retry(exc=e)                     # exponential backoff
    # sau 5 lần fail → task vào dead-letter, alert HR/IT
```

- **Idempotent gửi mail**: kiểm `email_status` trước khi gửi (tránh gửi 2 lần khi retry).
- **Dead-letter**: quá max_retries → set `FAILED`, tạo notification cho HR xử lý thủ công.

---

## 3.6. Audit Logging System

### Nguyên tắc: Immutable + Event-driven + Masked

```
                    ┌────────────────────────────────────────────┐
   mutating request │  middleware/audit.py                        │
   ───────────────► │  - bắt method POST/PUT/PATCH/DELETE         │
                    │  - lấy actor, ip, ua, request_id            │
                    └───────────────┬────────────────────────────┘
                                    │
   service layer ───────────────────┼──► audit.recorder.record(
   (biết old/new value)             │       action, entity, entity_id,
                                    │       old_value, new_value)
                                    ▼
                          ┌──────────────────────┐
                          │ mask sensitive (lương,│
                          │ CCCD → '***')         │
                          └──────────┬───────────┘
                                    ▼
                          INSERT audit_logs (chỉ INSERT)
                          (DB rule chặn UPDATE/DELETE)
```

### Middleware strategy + service-level
- **Middleware** ghi audit "thô" cho mọi request mutating (ai, khi nào, IP, endpoint). Đủ cho truy vết truy cập.
- **Service-level** ghi audit "giàu" có `old_value`/`new_value` cho entity quan trọng (employee, payroll, salary) — vì chỉ service mới biết giá trị trước/sau.
- **VIEW_SENSITIVE**: xem lương/CCCD giải mã → ghi audit dù là GET.

```python
# audit/recorder.py
SENSITIVE_KEYS = {"base_salary", "net_amount", "national_id", "bank_account", "phone"}

def mask(d: dict | None) -> dict | None:
    if not d: return d
    return {k: ("***" if k in SENSITIVE_KEYS else v) for k, v in d.items()}

async def record(db, *, actor_id, action, entity, entity_id,
                 old=None, new=None, ip=None, ua=None):
    await db.execute(insert(AuditLog).values(
        actor_id=actor_id, action=action, entity=entity, entity_id=str(entity_id),
        old_value=mask(old), new_value=mask(new), ip=ip, user_agent=ua))
    # KHÔNG commit riêng — đi cùng transaction nghiệp vụ để nhất quán
```

### Change tracking old/new (trong service)

```python
async def update_employee(self, id, patch, actor, ip):
    emp = await self.repo.get(id)
    old = snapshot(emp, fields=patch.keys())
    apply_patch(emp, patch)
    await self.repo.flush()
    new = snapshot(emp, fields=patch.keys())
    await record(self.db, actor_id=actor.id, action="UPDATE",
                 entity="employees", entity_id=id, old=old, new=new, ip=ip)
    await self.db.commit()
```

### DB protection strategy (immutable)
```sql
-- 1. App role chỉ SELECT/INSERT
REVOKE UPDATE, DELETE ON audit_logs FROM hrm_app;
GRANT  SELECT, INSERT ON audit_logs TO hrm_app;
-- 2. Rule chặn cứng kể cả nhầm lẫn
CREATE RULE audit_no_update AS ON UPDATE TO audit_logs DO INSTEAD NOTHING;
CREATE RULE audit_no_delete AS ON DELETE TO audit_logs DO INSTEAD NOTHING;
```
- Partition theo tháng → archive partition cũ bằng role DBA tách biệt (có quy trình + log ngoài).
- Tùy chọn nâng cao: định kỳ tính hash chuỗi (mỗi row chứa `prev_hash`) → phát hiện can thiệp (tamper-evident chain).

### Log query strategy
- Index `(entity, entity_id, created_at DESC)` → truy vết lịch sử 1 bản ghi nhanh.
- API `/audit?entity=&entity_id=&actor=&from=&to=` (quyền `audit:read`, thường chỉ ADMIN).
- Query xuyên nhiều partition → luôn kèm filter thời gian để partition pruning.

→ Tiếp: [Phần 4 — Frontend](04-frontend.md), [Phần 5 — DevOps](05-devops.md).
