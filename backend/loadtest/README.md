# Load testing

Two complementary tools:

| Tool | What it measures |
|---|---|
| `seed_payroll.py` | Batch payroll throughput — seed N employees, time a full `calculate_run`. |
| `locustfile.py` | Interactive API load — concurrent users hitting read endpoints. |

## 1. Payroll batch benchmark (10k employees)

```bash
# Inside the backend env with the DB reachable (DATABASE_URL set):
python -m loadtest.seed_payroll seed --count 10000 --period 2026-05
python -m loadtest.seed_payroll bench --period 2026-05
# -> "Calculated 10000 employees in N.NNs (X,XXX emp/s) [run #1]"
```

`bench` measures the **single-process** baseline (one Python worker evaluating
every formula). In production the same `calculate_run` is sharded across the
Celery `payroll` queue via a chord (`app.workers.payroll_tasks.run_payroll`,
chunk size 500), so wall-clock scales with the number of payroll workers:

```
10k employees / 500 per chunk = 20 chunks → run in parallel across N workers.
```

To exercise the distributed path, enqueue:

```python
from app.workers.payroll_tasks import run_payroll
run_payroll.delay(run_id, employee_ids)   # fan-out + finalize callback
```

## 2. Interactive API load (locust)

```bash
pip install ".[loadtest]"
LOADTEST_USER=admin LOADTEST_PASS='ChangeMe!123' \
  locust -f loadtest/locustfile.py --host http://localhost:8000
# open http://localhost:8089, set users + spawn rate
```

## Tuning knobs when results disappoint

- **DB pool**: `DB_POOL_SIZE` / `DB_MAX_OVERFLOW`, and put pgbouncer in front.
- **Payroll workers**: scale the `worker` service on the `payroll` queue.
- **Chunk size**: `CHUNK_SIZE` in `app/workers/payroll_tasks.py`.
- **Indexes**: payroll reads `attendance_monthly` + `payroll_input_values` by
  (employee, period) — both are indexed.
