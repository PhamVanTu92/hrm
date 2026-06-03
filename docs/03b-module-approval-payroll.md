# PHẦN 3B — MODULE: APPROVAL WORKFLOW & DYNAMIC PAYROLL ENGINE

---

## 3.3. Multi-level Approval Workflow Engine

### Mô hình: workflow định nghĩa bằng dữ liệu (không hardcode chain)

```
approval_workflows (target_type=LEAVE/BENEFIT)
   └─ approval_workflow_steps (step_order, approver_type, sla_hours)
        approver_type ∈ {MANAGER, ROLE, SPECIFIC_USER}

Khi tạo đơn → tạo approval_instances (current_step=1, IN_PROGRESS)
            → tạo approval_step_instances cho từng step (resolve approver thực)
```

### State machine

```
            create
             │
             ▼
        ┌─────────┐   approve(step<last)   ┌─────────────┐
        │ PENDING ├───────────────────────►│ IN_PROGRESS │
        └────┬────┘                         └──────┬──────┘
             │                          approve(last step)│
             │ reject (bất kỳ step)              │ approve
             ▼                                   ▼
        ┌──────────┐                       ┌──────────┐
        │ REJECTED │                       │ APPROVED │──► publish LeaveApproved/BenefitApproved
        └──────────┘                       └──────────┘
             ▲
             │ cancel (chỉ khi PENDING/IN_PROGRESS, bởi người tạo)
        ┌──────────┐
        │ CANCELLED│
        └──────────┘
```

**Trạng thái hợp lệ & transition:**

| Từ | Hành động | Tới | Ai |
|---|---|---|---|
| PENDING/IN_PROGRESS | approve (chưa step cuối) | IN_PROGRESS (current_step++) | approver step hiện tại |
| IN_PROGRESS | approve (step cuối) | APPROVED | approver cuối (HR) |
| bất kỳ active | reject | REJECTED | approver step hiện tại |
| PENDING/IN_PROGRESS | cancel | CANCELLED | người tạo đơn |
| IN_PROGRESS | escalate (quá SLA) | IN_PROGRESS (chuyển approver) | system (beat) |

### Resolve approver động

```python
def resolve_approver(step, employee) -> int:        # trả user_id
    if step.approver_type == "MANAGER":
        return employee.manager.user_id              # cấp trên trực tiếp (động theo NV)
    if step.approver_type == "ROLE":
        return pick_user_by_role(step.approver_ref)  # vd 'HR'
    if step.approver_type == "SPECIFIC_USER":
        return int(step.approver_ref)
```

### Approval sequence logic (pseudo code)

```python
def approve(instance_id, actor, comment):
    inst = lock_row(instance_id)                     # SELECT ... FOR UPDATE (chống race)
    step = current_step_instance(inst)
    assert step.approver_user_id == actor.id, "Không phải người duyệt"
    assert inst.status == "IN_PROGRESS", "Đơn không ở trạng thái duyệt"

    step.action="APPROVE"; step.comment=comment; step.acted_at=now()

    if is_last_step(inst):
        inst.status="APPROVED"; inst.completed_at=now()
        target = load_target(inst)                   # leave_request / benefit_request
        target.status="APPROVED"
        publish(build_event(target))                 # LeaveApproved / BenefitApproved
    else:
        inst.current_step += 1
        next_step = activate_next_step(inst)         # set approver + due_at (SLA)
        notify(next_step.approver_user_id, "Bạn có đơn cần duyệt")
    audit(actor, "APPROVE", "approval_instance", inst.id)
```

### Escalation (SLA quá hạn) — Celery beat

```python
@celery.task
def check_escalations():
    for step in overdue_steps():                     # due_at < now AND action IS NULL
        # chuyển lên cấp cao hơn hoặc nhắc lại
        escalate_to = manager_of(step.approver_user_id) or hr_admin()
        reassign(step, escalate_to)
        notify(escalate_to, "Đơn quá hạn duyệt cần xử lý")
        audit(SYSTEM, "ESCALATE", "approval_step_instance", step.id)
```

### Chế độ nâng cao tác động payroll
Khi `BenefitApproved(MATERNITY)` → service ghi cấu hình vào period áp dụng:
```python
@subscribe(BenefitApproved)
async def on_benefit_approved(e):
    if e.benefit_code == "MATERNITY":
        # khóa cách tính lương: lương công ty = 0, gắn thẻ BHXH
        await PayrollConfigService.set_override(
            employee_id=e.employee_id, period_range=(e.start, e.end),
            override={"company_salary": 0, "bhxh_tag": True})
```
→ Payroll engine đọc override này khi build context (xem §3.4).

---

## 3.4. Dynamic Payroll Engine (module quan trọng nhất)

### Tổng quan execution

```
1. Build variable context (mỗi NV):
     - base vars: luong_cung (giải mã), cong_chuan, cong_thuc_te (từ attendance_monthly)
     - component vars: thuong_nong, phu_cap_* (từ assignments + payroll_input_values, coalesce 0)
     - override: maternity → company_salary=0
2. Load formulas (period) → parse → build dependency graph → topo sort
3. Evaluate theo thứ tự topo bằng SimpleEval (sandbox)
4. Ghi payroll_run_items: input_snapshot + result (reproducible)
```

### Thư viện parser/evaluator: **simpleeval** (chọn)

| Lựa chọn | Ưu | Nhược |
|---|---|---|
| **simpleeval** (chọn) | An toàn (whitelist op/func), nhẹ, đủ cho biểu thức số học + if | Không hỗ trợ cú pháp phức tạp |
| `asteval` | Mạnh hơn (gần Python) | Bề mặt tấn công lớn hơn |
| `eval()` thuần | — | **TUYỆT ĐỐI KHÔNG** (RCE) |
| Tự viết AST parser | Kiểm soát tối đa | Tốn công, dễ bug |

**Cấu hình SimpleEval an toàn:**
```python
from simpleeval import SimpleEval
def make_evaluator(names: dict) -> SimpleEval:
    s = SimpleEval()
    s.names = names                              # biến số
    s.functions = {                              # whitelist function
        "min": min, "max": max, "round": round, "abs": abs,
        "if": lambda c,a,b: a if c else b,
    }
    # CẤM: attribute access, comprehension, import, lambda người dùng
    s.MAX_STRING_LENGTH = 1000
    return s
```

### Salary component system
- `salary_components.var_code` = biến trong công thức (vd `thuong_nong`). HR tạo khoản → auto sinh `var_code` (slugify + check unique).
- `value_type`: `INPUT` (import Excel), `FIXED` (giá trị cố định), `FORMULA` (tự là biểu thức).
- `salary_component_assignments`: gán scope ALL/DEPARTMENT/POSITION/EMPLOYEE + hiệu lực thời gian.

### Build variable context (coalesce 0)

```python
def build_context(employee, period) -> dict:
    ctx = {}
    # 1. base
    ctx["luong_cung"]    = decrypt_decimal(employee.enc_base_salary)
    m = monthly(employee.id, period)
    ctx["cong_chuan"]    = m.standard_days
    ctx["cong_thuc_te"]  = m.actual_days
    ctx["ot_gio"]        = m.ot_hours
    # 2. components áp dụng cho NV (resolve scope)
    for comp in components_for(employee, period):     # ALL∪DEPT∪POS∪EMP
        if comp.value_type == "INPUT":
            ctx[comp.var_code] = input_value(period, employee.id, comp.id) or 0  # coalesce 0
        elif comp.value_type == "FIXED":
            ctx[comp.var_code] = comp.default_value
        # FORMULA components added as formulas in graph
    # 3. override (maternity...)
    apply_overrides(ctx, employee, period)            # company_salary=0...
    return ctx
```

### Dependency graph & topo sort (tránh circular dependency)

```python
import ast, networkx as nx
def extract_vars(expr: str) -> set[str]:
    return {n.id for n in ast.walk(ast.parse(expr, mode="eval"))
            if isinstance(n, ast.Name)}

def build_eval_order(formulas: list[Formula], base_vars: set[str]) -> list[str]:
    g = nx.DiGraph()
    defined = {f.target_var for f in formulas}
    for f in formulas:
        g.add_node(f.target_var)
        for v in extract_vars(f.expression):
            if v in defined:                         # chỉ phụ thuộc biến tự định nghĩa
                g.add_edge(v, f.target_var)          # v phải tính trước target
            elif v not in base_vars:
                raise DomainError(f"Biến '{v}' không tồn tại trong công thức {f.target_var}")
    if not nx.is_directed_acyclic_graph(g):
        cycle = nx.find_cycle(g)
        raise DomainError("Công thức bị phụ thuộc vòng", details={"cycle": cycle})
    return list(nx.topological_sort(g))              # thứ tự an toàn
```

> **Strategy tránh circular:** validate đồ thị **ngay khi HR lưu công thức** (API `/formulas`), không đợi tới lúc chạy. DAG check + báo lỗi vòng cụ thể.

### Pseudo code tính lương (đầy đủ)

```python
def calculate_employee(employee, period, formulas, eval_order) -> dict:
    ctx = build_context(employee, period)            # input snapshot
    formula_by_target = {f.target_var: f for f in formulas}
    for var in eval_order:                           # topo order
        expr = formula_by_target[var].expression
        ev = make_evaluator(ctx)
        try:
            ctx[var] = round(ev.eval(expr), 2)
        except Exception as ex:
            raise DomainError(f"Lỗi công thức '{var}': {ex}")
    return ctx                                        # ctx['TONG_LUONG'] là kết quả cuối

def run_payroll(period, run_id, employee_ids):
    formulas  = load_formulas(period)
    order     = build_eval_order(formulas, BASE_VARS)
    for emp in employees(employee_ids):
        ctx = calculate_employee(emp, period, formulas, order)
        save_run_item(run_id, emp.id,
            input_snapshot=extract_inputs(ctx),       # mọi biến đầu vào
            result=ctx,
            net_amount=encrypt(str(ctx["TONG_LUONG"])))
```

### Excel import architecture

```
HR upload .xlsx ──► validate header (var_code khớp salary_components value_type=INPUT)
                ──► map cột → (employee_code, component) ──► validate số liệu
                ──► UPSERT payroll_input_values (period, emp, comp)
                ──► report: dòng lỗi (NV không tồn tại, sai số), dòng OK
```
- Lib: **openpyxl** (đọc/ghi .xlsx, streaming `read_only=True` cho file lớn).
- Template tải về từ hệ thống (cột = các `var_code` INPUT đang active).
- Validate nghiêm: NV không tồn tại → reject dòng; giá trị âm/không phải số → reject; coalesce 0 cho NV không có dòng.

### Payroll snapshot strategy (reproducibility)
- Khi tạo run: lưu `payroll_runs.formula_snapshot` (đóng băng toàn bộ công thức) + mỗi item `input_snapshot` (mọi biến). → Tái tính cho ra **kết quả y hệt** dù sau này HR sửa công thức/đổi lương.
- Đây là yêu cầu kiểm toán: phiếu lương đã phát hành phải tái dựng được.

### Payroll locking
```
DRAFT ──lock──► LOCKED (snapshot + payroll_periods.status=LOCKED, attendance_monthly.locked=TRUE)
LOCKED: không cho recalc/sửa input. Chỉ flow CONFIRMED (NV xác nhận) hoặc CANCEL.
```
- Lock dùng transaction + `SELECT ... FOR UPDATE` trên `payroll_periods`.
- Concurrency: chỉ 1 run active/period (UNIQUE partial index `WHERE status IN ('DRAFT','LOCKED')`).

### Payroll recalculation & rollback
- **Recalc**: chỉ khi `DRAFT`. Xóa items cũ → tính lại. (LOCKED không recalc.)
- **Rollback (cancel)**:
  ```
  cancel(run): 
    assert status in (DRAFT, LOCKED) and not yet CONFIRMED-sent
    set status=CANCELLED
    set payroll_periods.status=OPEN, attendance_monthly.locked=FALSE
    audit(action=CANCEL, old=snapshot)
    # items giữ lại (immutable history) nhưng đánh dấu CANCELLED
  ```
- Nếu phiếu đã gửi NV (CONFIRMED + email SENT) → **không rollback "im lặng"**; phải tạo **kỳ điều chỉnh (adjustment run)** để truy vết.

### Caching strategy
| Cache (Redis) | TTL | Invalidation |
|---|---|---|
| Master data: ca làm, ngày lễ, salary_components def | 1h | Event khi HR sửa config |
| Eval order (topo) theo period | tới khi lock | Khi sửa formula của period |
| RBAC permissions theo user | 10m | Khi đổi role |
- **KHÔNG cache kết quả lương** (nhạy cảm + phải snapshot ở DB).

→ Tiếp: [Phần 3C — Payslip Automation & Audit Logging](03c-module-payslip-audit.md).
