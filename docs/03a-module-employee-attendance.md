# PHẦN 3A — MODULE: EMPLOYEE DYNAMIC PROFILE & ATTENDANCE

---

## 3.1. Employee Dynamic Profile (Hồ sơ động)

### Bài toán
HR cần tự thêm Category & Field runtime (TEXT/NUMBER/DATE/SELECT/BOOLEAN), đánh dấu bắt buộc/mã hóa, **không sửa schema DB**.

### Chiến lược: Metadata-driven + JSONB (EAV cải tiến)

```
profile_categories ──1:N──► profile_fields  (metadata: định nghĩa form)
                                   │
employees ──1:1──► employee_dynamic_profiles.data (JSONB: giá trị thực)
```

- **Metadata** (`profile_fields`): mô tả field → frontend render form động, backend validate động.
- **Value** (`data` JSONB): `{ "field_key": value }`. Field mã hóa → `{ "so_cmnd_vo": "enc:BASE64..." }`.

**Vì sao JSONB chứ không EAV thuần (bảng value dọc)?**

| | JSONB (chọn) | EAV (bảng dọc) |
|---|---|---|
| Đọc cả hồ sơ | 1 row, 1 query | N row, phải pivot |
| Thêm field | Không đổi schema | Không đổi schema |
| Search 1 field | GIN index `@>` | Index tốt nhưng query phức |
| Validate | Tầng app theo metadata | Tầng app |
| Ràng buộc kiểu | Yếu (app lo) | Yếu |

→ JSONB thắng cho use-case "đọc nguyên hồ sơ" phổ biến nhất.

### Field validation (động, theo metadata)

```python
# modules/employee/profile_validator.py
def validate_dynamic(fields: list[ProfileField], payload: dict) -> dict:
    errors, clean = {}, {}
    for f in fields:
        v = payload.get(f.field_key)
        if f.is_required and (v is None or v == ""):
            errors[f.field_key] = "Bắt buộc nhập"; continue
        if v is None: continue
        # ép kiểu theo data_type
        try:
            v = cast_value(f.data_type, v)          # TEXT/NUMBER/DATE/SELECT/BOOLEAN
        except ValueError:
            errors[f.field_key] = f"Sai kiểu {f.data_type}"; continue
        # rule bổ sung trong f.validation (regex/min/max)
        if not check_rules(f.validation, v):
            errors[f.field_key] = "Không hợp lệ"; continue
        if f.data_type == "SELECT" and v not in (f.options or []):
            errors[f.field_key] = "Giá trị không trong danh sách"; continue
        clean[f.field_key] = v
    if errors: raise DomainError("Hồ sơ không hợp lệ", details=errors)
    return clean
```

### Encryption fields trong JSONB

```python
def persist_profile(clean: dict, fields_by_key: dict) -> dict:
    out = {}
    for k, v in clean.items():
        f = fields_by_key[k]
        if f.is_encrypted:
            out[k] = "enc:" + base64.b64encode(encrypt(str(v))).decode()
        else:
            out[k] = v
    return out                                   # ghi vào data JSONB

def read_profile(data: dict, fields_by_key, actor) -> dict:
    out = {}
    for k, v in data.items():
        f = fields_by_key.get(k)
        if f and f.is_encrypted:
            if "salary:view_sensitive" not in actor.perms:
                out[k] = "***"                   # masked
            else:
                out[k] = decrypt(base64.b64decode(v[4:]))   # bỏ prefix 'enc:'
                audit_view_sensitive(actor, "employee_profile", k)
        else:
            out[k] = v
    return out
```

### Dynamic form rendering (FE)
Frontend GET `/dynamic-fields` → nhận metadata → render form theo `data_type`:
- TEXT→input, NUMBER→number, DATE→datepicker, SELECT→dropdown(options), BOOLEAN→switch.
- `is_required`→validation FE, `is_encrypted`→hiển thị icon khóa.

### Search strategy
- Field thường (không mã hóa): query GIN JSONB.
  ```sql
  SELECT employee_id FROM employee_dynamic_profiles
  WHERE data @> '{"tinh_trang_hon_nhan":"Đã kết hôn"}';
  ```
- Field mã hóa: **KHÔNG search được** trên ciphertext (đúng theo bảo mật). Nếu bắt buộc search trên 1 field nhạy cảm (vd CCCD) → lưu thêm cột **blind index** = HMAC-SHA256(value, key) để so khớp chính xác (equality) mà không lộ giá trị.

---

## 3.2. Attendance System

### Kiến trúc pipeline 3 tầng

```
 ┌───────────────┐  pull 23:00   ┌────────────────────┐  normalize  ┌──────────────────┐  aggregate
 │ Máy chấm công │ ────────────► │ attendance_raw_logs │ ──────────► │ attendance_daily  │ ──────────►
 │ (.mdb/SQL/IP) │   (adapter)   │  (thô, idempotent)  │  (1/ngày)   │  (công ngày)      │
 └───────────────┘               └────────────────────┘             └──────────────────┘
                                                                            │ + leave/benefit approved
                                                                            ▼
                                                                  ┌──────────────────────┐
                                                                  │ attendance_monthly    │
                                                                  │  (công thực tế tháng) │
                                                                  └──────────────────────┘
```

### Adapter máy chấm công (Strategy pattern)

```python
# integrations/timeclock/base.py
class TimeclockAdapter(Protocol):
    def fetch_logs(self, since: datetime) -> list[RawPunch]: ...

# mdb_adapter.py — đọc .mdb qua pyodbc (Access Driver) hoặc mdbtools (Linux)
# sqlexpress_adapter.py — pyodbc DSN tới SQL Express
# tcp_adapter.py — protocol ZKTeco (pyzk) kết nối IP:port
```

> Cấu hình adapter lưu ở `attendance_devices.config (JSONB)` → đổi máy/đổi cách kết nối không sửa code.

### Cronjob architecture (Celery Beat)

```python
# cronjobs/schedules.py
beat_schedule = {
    "pull-attendance-nightly": {
        "task": "workers.attendance_tasks.pull_all_devices",
        "schedule": crontab(hour=23, minute=0),
    },
    "create-next-partition": {
        "task": "workers.attendance_tasks.ensure_next_partition",
        "schedule": crontab(day_of_month=25, hour=1, minute=0),
    },
}
```

```python
# workers/attendance_tasks.py
@celery.task(bind=True, max_retries=3, default_retry_delay=300, queue="attendance")
def pull_all_devices(self):
    for dev in active_devices():
        pull_device.delay(dev.id)          # fan-out mỗi device 1 task → retry độc lập

@celery.task(bind=True, max_retries=3, queue="attendance")
def pull_device(self, device_id):
    try:
        adapter = build_adapter(device_id)
        since = last_ingest_time(device_id)
        punches = adapter.fetch_logs(since)
        bulk_upsert_raw_logs(device_id, punches)   # ON CONFLICT DO NOTHING (idempotent)
        normalize_daily.delay(device_id, since.date())
    except Exception as e:
        raise self.retry(exc=e)
```

### Raw log processing & shift calculation (pseudo code)

```
function normalize_day(employee, work_date, shift):
    punches = raw_logs(employee, work_date) sorted by punch_at
    if punches empty:
        if is_holiday(work_date): status=HOLIDAY, work=shift.holiday_value
        elif has_approved_leave(employee, work_date):
            status=LEAVE; work = leave_paid ? 1.0 : 0.0
        else: status=MISSING, work=0
        upsert_daily(...); return

    first_in = punches.first.punch_at
    last_out = punches.last.punch_at

    late  = max(0, minutes(first_in) - minutes(shift.start_time) - shift.late_grace_min)
    early = max(0, minutes(shift.end_time) - minutes(last_out))
    ot    = max(0, minutes(last_out) - minutes(shift.end_time))   # nếu có duyệt OT

    worked_min = (last_out - first_in) - shift.break_minutes
    required   = (shift.end_time - shift.start_time) - shift.break_minutes
    work_value = round_to_half( worked_min / required )           # 0 / 0.5 / 1

    upsert_daily(employee, work_date, first_in, last_out, late, early, ot, work_value,
                 status=NORMAL)   # UNIQUE(employee_id, work_date) → recompute an toàn
```

**Late/early/OT logic:**
- Đi muộn = giờ vào − giờ bắt đầu ca − grace.
- Về sớm = giờ kết thúc ca − giờ ra.
- OT = giờ ra − giờ kết thúc ca, **chỉ tính nếu có đơn OT được duyệt** (chống tự ý ở lại).

**Holiday handling:** ngày trong `holidays` & `is_paid` → công = 1 (hưởng nguyên lương) không cần quét.

**Leave compensation (bù công):** khi `LeaveApproved` event bắn ra → cập nhật `attendance_daily.status=LEAVE`, `work_value` theo loại phép → recompute `attendance_monthly`.

```python
# modules/attendance/events.py
@subscribe(LeaveApproved)
async def on_leave_approved(e: LeaveApproved):
    await AttendanceService.apply_leave(e.employee_id, e.start, e.end, e.leave_type)
    await AttendanceService.recompute_monthly(e.employee_id, e.period)
```

### Monthly aggregation (batch)

```sql
-- gom từ daily → monthly (chạy cuối tháng / on-demand)
INSERT INTO attendance_monthly (employee_id, period, standard_days, actual_days,
                                leave_days, paid_leave_days, ot_hours, late_count)
SELECT d.employee_id, :period,
       :standard_days,
       SUM(CASE WHEN d.status='NORMAL'  THEN d.work_value ELSE 0 END),
       SUM(CASE WHEN d.status='LEAVE'   THEN d.work_value ELSE 0 END),
       SUM(CASE WHEN d.status='LEAVE' AND d.work_value>0 THEN d.work_value ELSE 0 END),
       SUM(d.ot_minutes)/60.0,
       COUNT(*) FILTER (WHERE d.late_minutes > 0)
FROM attendance_daily d
WHERE date_trunc('month', d.work_date) = :month_start
GROUP BY d.employee_id
ON CONFLICT (employee_id, period) DO UPDATE SET
   actual_days=EXCLUDED.actual_days, leave_days=EXCLUDED.leave_days,
   paid_leave_days=EXCLUDED.paid_leave_days, ot_hours=EXCLUDED.ot_hours,
   late_count=EXCLUDED.late_count
WHERE attendance_monthly.locked = FALSE;       -- không ghi đè khi đã khóa
```

### Batch processing strategy
- **Idempotent**: mọi tầng dùng UNIQUE natural key + UPSERT → chạy lại không nhân đôi.
- **Fan-out theo device** → lỗi 1 máy không chặn máy khác; retry độc lập (exponential backoff).
- **Chunk theo NV** khi normalize 10k NV: chia batch 500, `group()` Celery.
- **Lock guard**: `attendance_monthly.locked=TRUE` sau khi payroll chốt → batch không ghi đè.
- **Reconciliation report**: so số bản ghi raw kéo về vs nguồn → cảnh báo thiếu.

→ Tiếp: [Phần 3B — Approval Workflow & Dynamic Payroll Engine](03b-module-approval-payroll.md).
