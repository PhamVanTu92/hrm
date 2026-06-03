# Deploy — newhrm.foxai.com.vn

This server already runs a **system nginx on :80/:443** and has many busy ports
(5432, 6379, 9000/9001, 3000, 8000, …). So the HRM stack publishes **no infra
ports**; its container nginx binds **127.0.0.1:8090**, and the host nginx
terminates TLS for the domain and proxies to it.

```
Internet ──TLS──▶ host nginx (443, newhrm.foxai.com.vn)
                       │ proxy_pass
                       ▼
                 127.0.0.1:8090  ──▶ container nginx ──┬── /      ▶ frontend:3000
                                                       └── /api   ▶ api:8000
```

## 1. DNS
Point `newhrm.foxai.com.vn` A-record to the server's public IP.

## 2. Clone + config (non-secret `.env`)
```bash
git clone <repo-url> /opt/hrm && cd /opt/hrm/backend
cat > .env <<'EOF'
APP_NAME=HRM
POSTGRES_USER=hrm
POSTGRES_DB=hrm
REDIS_URL=redis://redis:6379/0
RATE_LIMIT_REDIS_URL=redis://redis:6379/1
CELERY_BROKER_URL=redis://redis:6379/2
CELERY_RESULT_BACKEND=redis://redis:6379/3
S3_ENDPOINT=http://minio:9000
S3_BUCKET=hrm
S3_ACCESS_KEY=minioadmin
CORS_ORIGINS=https://newhrm.foxai.com.vn
TIMEZONE=Asia/Ho_Chi_Minh
# --- SSO (chỉ cần nếu bật) ---
SSO_ENABLED=true
MS_TENANT_ID=<tenant-id>
MS_CLIENT_ID=<client-id>
MS_CLIENT_SECRET=<client-secret>
MS_REDIRECT_URI=https://newhrm.foxai.com.vn/api/v1/auth/sso/callback
SSO_FRONTEND_REDIRECT=https://newhrm.foxai.com.vn/sso/callback
EOF
chmod 600 .env
```

## 3. Secrets (git-ignored)
```bash
mkdir -p secrets
PGPASS=$(openssl rand -hex 16)
echo -n "$PGPASS"                                               > secrets/postgres_password
echo -n "postgresql+asyncpg://hrm:${PGPASS}@pgbouncer:6432/hrm"  > secrets/database_url
python3 -c "import secrets;print(secrets.token_urlsafe(48),end='')" > secrets/jwt_secret_key
python3 -c "import secrets;print(secrets.token_hex(32),end='')"     > secrets/aes_key_hex
python3 -c "import secrets;print(secrets.token_hex(32),end='')"     > secrets/blind_index_key_hex
echo -n "minioadmin"                                            > secrets/s3_secret_key
chmod 600 secrets/*
```
> SSO client secret: add `MS_CLIENT_SECRET=<value>` to `.env` (step 2). The core
> secrets above stay in `./secrets/` (mounted at `/run/secrets`).

## 4. Build + run (the command)
```bash
cd /opt/hrm/backend
NEXT_PUBLIC_SSO_ENABLED=true \
  docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
```
Order is automatic: `db → migrate → bootstrap (seed RBAC) → api/worker/beat → frontend → nginx (127.0.0.1:8090)`.

Check: `docker compose -f docker-compose.yml -f docker-compose.server.yml ps`
and `curl -fsS http://127.0.0.1:8090/health`.

## 5. First-time data
```bash
DC="docker compose -f docker-compose.yml -f docker-compose.server.yml"
# Create the MinIO bucket for payslip PDFs:
$DC exec api python -c "from app.core.storage import storage; storage.ensure_bucket()"
# Create a real admin (production skips default accounts):
$DC exec api python -m scripts.create_superuser \
    --username admin --email admin@foxai.com.vn --password 'MatKhauManh!2026'
```

## 6. Host nginx vhost + TLS
```bash
sudo cp deploy/newhrm.foxai.com.vn.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/newhrm.foxai.com.vn.conf /etc/nginx/sites-enabled/
sudo certbot --nginx -d newhrm.foxai.com.vn      # issues cert + wires 443
sudo nginx -t && sudo systemctl reload nginx
```
(If certbot manages the file, ensure the `location /` still proxies to
`http://127.0.0.1:8090`.)

## 7. Verify
```bash
curl -fsS https://newhrm.foxai.com.vn/health
# open https://newhrm.foxai.com.vn  -> login (admin / MatKhauManh!2026, or Microsoft)
```

## 8. Microsoft Entra app registration (for SSO)
Redirect URI (Web): `https://newhrm.foxai.com.vn/api/v1/auth/sso/callback`
Permissions (delegated): `openid profile email`. Put tenant id, client id and
client secret in `.env` (step 2).

## Update later
```bash
cd /opt/hrm && git pull
cd backend && NEXT_PUBLIC_SSO_ENABLED=true \
  docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
```

## Notes
- Container nginx is bound to `127.0.0.1:8090` only — not exposed publicly.
- No HRM infra port is published; reach MinIO/Postgres via `docker compose exec`
  or an SSH tunnel if needed.
- Needs Docker Compose **v2.24+** (for the `!override` ports tag). Check:
  `docker compose version`.
