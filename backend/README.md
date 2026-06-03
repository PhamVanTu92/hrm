# HRM Backend

Production-ready backend scaffold for the in-house HRM system.

**Stack:** FastAPI · PostgreSQL 16 · SQLAlchemy 2.0 (async) · Alembic · Redis ·
Celery · Docker. **Architecture:** Modular Monolith + Clean/Layered + DDD
tactical (each `app/modules/<x>` is a bounded context).

---

## Layout

```
backend/
├── app/
│   ├── core/        # config, security, encryption, rbac, logging, redis, events
│   ├── db/          # Base, async session, mixins, BaseRepository, model registry
│   ├── middleware/  # rate limit, request context, secure headers
│   ├── audit/       # immutable audit log model, masking, recorder
│   ├── modules/     # bounded contexts
│   │   ├── auth/        # login/refresh/logout, JWT, RBAC
│   │   └── employee/    # employees + dynamic JSONB profiles, field encryption
│   ├── workers/     # Celery tasks: attendance, payroll, pdf, email, maintenance
│   ├── api/         # aggregate API router
│   └── main.py      # app factory + lifespan
├── migrations/      # Alembic (env.py, versions/0001_initial.py)
├── scripts/         # bootstrap.py (seed + default accounts), seed.py, create_superuser.py
├── Dockerfile               # multi-stage; one image for api/worker/beat
├── docker-compose.yml       # full stack (api, worker, beat, db, pgbouncer, redis, minio, nginx)
├── nginx.conf
├── .env.example
└── pyproject.toml
```

---

## Quick start (Docker — recommended)

```bash
cd backend
cp .env.example .env                       # then edit secrets (see below)

# Generate the two crypto keys and paste them into .env:
python -c "import secrets; print('AES_KEY_HEX=' + secrets.token_hex(32))"
python -c "import secrets; print('BLIND_INDEX_KEY_HEX=' + secrets.token_hex(32))"
# Also set a strong JWT_SECRET_KEY (>= 32 chars).

docker compose up -d --build               # builds api + frontend, migrates, starts everything
```

This brings up the **whole stack behind nginx** on one origin (default
`http://localhost`): the Next.js frontend at `/` and the FastAPI backend at
`/api`. Open **http://localhost** and log in. To show the Microsoft SSO button,
build with `NEXT_PUBLIC_SSO_ENABLED=true docker compose up -d --build`.

The `migrate` service runs `alembic upgrade head`, then the `bootstrap` service
seeds RBAC + **default login accounts** — both run automatically before
`api`/`worker` start (`depends_on: service_completed_successfully`). No manual
step needed.

### Default accounts (created by `scripts/bootstrap.py`)

| Username | Role | Quyền |
|----------|----------|-------|
| `admin` | ADMIN | full |
| `hr` | HR | employee/payroll/attendance/approval |
| `manager` | MANAGER | read + approve |
| `employee` | EMPLOYEE | self-service |

Password (all): **`Admin@12345`** (override via `DEFAULT_PASSWORD`). Đổi ngay
sau lần đăng nhập đầu. In production `bootstrap` refuses to run unless
`BOOTSTRAP_FORCE=1`. Re-run any time: `docker compose exec api python -m scripts.bootstrap`.

- App (FE):   http://localhost            (nginx → Next.js)
- API:        http://localhost/api/v1     (nginx → FastAPI)
- Health:     http://localhost/health
- OpenAPI:    http://localhost/docs        (disabled in production)
- MinIO UI:   http://localhost:9001

---

## Quick start (local, no Docker)

Requires Python 3.12, a running PostgreSQL 16 and Redis.

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate    # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"

cp .env.example .env                                 # point DATABASE_URL/REDIS_URL at localhost
# e.g. DATABASE_URL=postgresql+asyncpg://hrm:hrm_password@localhost:5432/hrm

alembic upgrade head
python -m scripts.bootstrap          # seed RBAC + default accounts (admin/hr/manager/employee)

uvicorn app.main:app --reload --port 8000
```

Then log in as `admin` / `Admin@12345` (see the default-accounts table above).

In separate terminals, the background workers:

```bash
celery -A app.core.celery_app worker --loglevel=info -Q default,attendance,payroll,pdf,email
celery -A app.core.celery_app beat   --loglevel=info -S redbeat.RedBeatScheduler
```

---

## Configuration

All config is environment-driven and validated by Pydantic Settings
(`app/core/config.py`). See `.env.example` for every variable. Required secrets
with no safe default:

| Variable              | Notes                                              |
|-----------------------|----------------------------------------------------|
| `JWT_SECRET_KEY`      | ≥ 32 chars, random                                 |
| `AES_KEY_HEX`         | 64 hex chars (32 bytes) — AES-256 field encryption |
| `BLIND_INDEX_KEY_HEX` | 64 hex chars — HMAC key for searchable ciphertext  |
| `DATABASE_URL`        | `postgresql+asyncpg://…`                           |

Redis logical DBs: `0` cache · `1` rate-limit · `2` Celery broker · `3` results.

---

## Database migrations

```bash
alembic revision --autogenerate -m "add <thing>"   # generate from model changes
alembic upgrade head                                # apply
alembic downgrade -1                                # roll back one
```

`migrations/env.py` reads `settings.sync_database_url` (psycopg) and the
metadata from `app/db/registry.py` — import every new model there so
autogenerate sees it.

> **audit_logs** is range-partitioned by month with DB rules blocking
> UPDATE/DELETE (immutability). The `ensure_next_partitions` beat task
> pre-creates next month's partition on the 25th.

---

## Security model (where to look)

| Concern                 | Implementation                                            |
|-------------------------|-----------------------------------------------------------|
| Password hashing        | Argon2id — `app/core/security.py`                         |
| Access tokens           | JWT (15 min), roles+perms in claims — `security.py`       |
| Refresh tokens          | Opaque, SHA-256 at rest, rotation + reuse detection       |
| RBAC                    | `require_perm()` dependency — `app/core/rbac.py`          |
| Field encryption        | AES-256-GCM, versioned — `app/core/encryption.py`         |
| Searchable ciphertext   | Blind index (HMAC-SHA256) — `encryption.py`               |
| Anti-bruteforce         | Account lock after N fails — `modules/auth/service.py`    |
| Rate limiting           | slowapi + Redis — `app/middleware/rate_limit.py`          |
| Secure headers          | `app/middleware/secure_headers.py`                        |
| Audit trail             | immutable log + masking — `app/audit/`                    |

---

## Tests & quality

```bash
pytest            # uses testcontainers for a real Postgres
ruff check .      # lint (includes bandit "S" rules)
mypy app          # type check
```

---

## Scaling notes

- **Workers:** the compose `worker` consumes all queues. In production run one
  worker *service per queue* (`-Q payroll` etc.) and scale replicas
  independently — payroll/pdf are CPU-heavy, email is I/O-heavy.
- **Connections:** the app talks to **pgbouncer** (transaction pooling), not
  Postgres directly, so thousands of clients map to a small server pool.
- **Reads:** set `DATABASE_REPLICA_URL` to route read-only queries
  (`get_read_db`) to a replica.
