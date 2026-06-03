# PHẦN 5 — DEVOPS & DEPLOYMENT

---

## 5.1. Deployment architecture

```
                    Internet
                       │ HTTPS (443)
                ┌──────▼───────┐
                │    Nginx     │  TLS (Let's Encrypt), gzip, rate-limit, static FE
                └──┬────────┬──┘
                   │        │
          /api/*   │        │  / (frontend)
          ┌────────▼──┐  ┌──▼─────────┐
          │ FastAPI   │  │ Next.js    │
          │ (gunicorn │  │ (node/     │
          │ +uvicorn  │  │  static)   │
          │ workers)  │  └────────────┘
          └────┬──────┘
   ┌───────────┼───────────┬──────────────┐
   ▼           ▼           ▼              ▼
┌──────┐  ┌────────┐  ┌─────────┐  ┌──────────────┐
│ PgB  │  │ Redis  │  │ MinIO   │  │ Celery worker│
│ ouncer│ │        │  │ /S3     │  │ + beat       │
└──┬───┘  └────────┘  └─────────┘  └──────────────┘
   ▼
┌──────────────┐ stream  ┌──────────────┐
│ Postgres     │────────►│ Postgres     │
│ primary      │         │ read replica │
└──────────────┘         └──────────────┘
```

## 5.2. Docker & Docker Compose

```dockerfile
# Dockerfile (backend) — multi-stage
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 \  # WeasyPrint deps
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev
COPY app/ ./app/
COPY migrations/ ./migrations/
# non-root
RUN useradd -m appuser && chown -R appuser /app
USER appuser
CMD ["gunicorn","app.main:app","-k","uvicorn.workers.UvicornWorker",\
     "-w","4","-b","0.0.0.0:8000","--timeout","120"]
```

```yaml
# docker-compose.yml (prod)
services:
  api:
    build: .
    env_file: .env
    depends_on: [db, redis]
    deploy: { replicas: 2 }
    restart: always
  worker:
    build: .
    command: celery -A app.core.celery_app worker -Q default,payroll,pdf,email,attendance -c 4
    env_file: .env
    depends_on: [db, redis]
    restart: always
  beat:
    build: .
    command: celery -A app.core.celery_app beat -S redbeat.RedBeatScheduler
    env_file: .env
    depends_on: [redis]
    restart: always
  db:
    image: postgres:16
    environment: { POSTGRES_DB: hrm, POSTGRES_USER: hrm, POSTGRES_PASSWORD_FILE: /run/secrets/db_pw }
    volumes: ["pgdata:/var/lib/postgresql/data"]
    secrets: [db_pw]
    restart: always
  pgbouncer:
    image: edoburu/pgbouncer
    environment: { DATABASE_URL: "postgres://hrm@db:5432/hrm" }
    depends_on: [db]
  redis:
    image: redis:7-alpine
    command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru
    volumes: ["redisdata:/data"]
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    volumes: ["miniodata:/data"]
  nginx:
    image: nginx:alpine
    ports: ["80:80","443:443"]
    volumes: ["./nginx.conf:/etc/nginx/nginx.conf:ro","./certs:/etc/letsencrypt:ro"]
    depends_on: [api]
volumes: { pgdata:, redisdata:, miniodata: }
secrets: { db_pw: { file: ./secrets/db_pw.txt } }
```

## 5.3. Nginx + SSL

```nginx
server {
  listen 443 ssl http2;
  server_name hrm.company.vn;
  ssl_certificate     /etc/letsencrypt/live/hrm/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/hrm/privkey.pem;
  client_max_body_size 25M;                     # upload Excel/scan minh chứng

  location /api/ {
    limit_req zone=api burst=20 nodelay;        # rate-limit L7
    proxy_pass http://api:8000;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }
  location / { proxy_pass http://frontend:3000; }
}
# http { limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s; }
```
- SSL: **Let's Encrypt** + certbot auto-renew (cron). HSTS header bật.

## 5.4. CI/CD (GitHub Actions / GitLab CI)

```yaml
# .github/workflows/ci.yml (rút gọn)
jobs:
  test:
    services: { postgres: {image: postgres:16}, redis: {image: redis:7} }
    steps:
      - uses: actions/checkout@v4
      - run: pip install uv && uv sync
      - run: uv run ruff check . && uv run mypy app
      - run: uv run alembic upgrade head
      - run: uv run pytest --cov=app --cov-fail-under=75
  build-deploy:
    needs: test
    if: github.ref == 'refs/heads/main'
    steps:
      - run: docker build -t registry/hrm-api:$GITHUB_SHA .
      - run: docker push registry/hrm-api:$GITHUB_SHA
      - run: ssh prod "cd /opt/hrm && docker compose pull && \
             docker compose run --rm api alembic upgrade head && \
             docker compose up -d"
```
- Pipeline: lint(ruff)+type(mypy) → test(pytest) → build image → migrate → deploy.
- Migration chạy **trước** khi up app mới (zero-downtime: migration phải backward-compatible).

## 5.5. Production env variables

```bash
# .env (prod — inject qua secret, KHÔNG commit)
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://hrm:***@pgbouncer:6432/hrm?ssl=require
DATABASE_REPLICA_URL=postgresql+asyncpg://hrm:***@replica:5432/hrm
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/2
JWT_SECRET_KEY=<64 hex random>
AES_KEY_HEX=<64 hex = 32 bytes>
ACCESS_TOKEN_TTL_MIN=15
REFRESH_TOKEN_TTL_DAYS=7
SMTP_HOST=... SMTP_PORT=587 SMTP_USER=... SMTP_PASS=...
S3_ENDPOINT=http://minio:9000 S3_BUCKET=hrm S3_KEY=... S3_SECRET=...
SENTRY_DSN=...
CORS_ORIGINS=https://hrm.company.vn
```

## 5.6. Auto backup PostgreSQL

```bash
# scripts/backup.sh — cron 02:00 hàng ngày
set -euo pipefail
TS=$(date +%F_%H%M)
pg_dump -Fc -h db -U hrm hrm | \
  openssl enc -aes-256-cbc -salt -pass file:/run/secrets/backup_key \
  > /backups/hrm_$TS.dump.enc          # backup MÃ HÓA (an toàn khi rò rỉ)
# upload offsite
aws s3 cp /backups/hrm_$TS.dump.enc s3://hrm-backup/ 
# retention: xóa > 30 ngày
find /backups -name '*.dump.enc' -mtime +30 -delete
```
- **3-2-1 rule**: bản local + offsite (S3) + định kỳ test restore.
- WAL archiving / PITR (point-in-time recovery) cho prod nghiêm túc.
- **Test restore hàng tháng** (backup không test = không có backup).

## 5.7. Monitoring & Logging

| Lớp | Công cụ | Theo dõi |
|---|---|---|
| App metrics | Prometheus + `prometheus-fastapi-instrumentator` | req rate, latency, error 5xx |
| Dashboard | Grafana | API, DB connections, Celery queue depth |
| Error tracking | Sentry | exception + trace, alert |
| Logs | structlog (JSON) → Loki / ELK | correlation theo `request_id` |
| Celery | Flower | task success/fail, queue backlog |
| DB | `pg_stat_statements` | slow query |
| Uptime | healthcheck `/health` + alert | liveness/readiness |

```python
# /health endpoint: check DB + Redis ping → 200/503
```

## 5.8. Scaling strategy (tóm tắt thực thi)
- **App**: tăng `replicas` + gunicorn workers sau Nginh LB. Stateless.
- **DB**: read replica cho query đọc nặng (`DATABASE_REPLICA_URL` cho service read-only). PgBouncer pool. Partition log tables.
- **Worker**: scale theo queue — payroll/pdf nhiều worker khi chạy lương. RedBeat lock chống beat trùng.
- **Cache**: Redis cho RBAC, master data, rate-limit.
- Chi tiết ngưỡng 100→10k ở [Phần 1 §1.6](01-kien-truc-tong-quan.md).

→ Tiếp: [Phần 6-10](06-10-testing-roadmap-cost-risk-tech.md).
