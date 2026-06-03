# Production hardening

How to run the HRM backend safely in production. Pairs with
`docker-compose.prod.yml`, `nginx.prod.conf`, and the scripts under `scripts/`.

## 1. Secrets (Vault / Docker secrets)

Secrets are **never** baked into images or committed. The app reads them from
files when `SECRETS_DIR` is set (`app/core/config.py` → `secrets_dir`):

```
SECRETS_DIR=/run/secrets   # Docker secrets mount it here
```

Provide one file per secret (filename = lowercase field name):
`database_url`, `jwt_secret_key`, `aes_key_hex`, `blind_index_key_hex`,
`s3_secret_key`, `postgres_password`. With Vault, render them via Vault Agent
templates into `/run/secrets` (or inject as Docker secrets). Env vars still
override files, so local dev is unchanged.

**Boot guard:** when `APP_ENV=production`, `Settings` refuses to start if it
detects placeholder secrets (sample JWT, repeated-char AES/blind keys, key
reuse, or `DEBUG=true`). This stops the classic "shipped the `.env.example`
keys" incident. Rotate `AES_KEY_HEX` by adding a new key version in
`app/core/encryption.py` (the ciphertext format is versioned).

## 2. TLS + edge

`nginx.prod.conf` terminates TLS on 443 (TLS 1.2/1.3), redirects 80→443, sets
HSTS, and restricts `/metrics` to private networks. Mount certs at
`./certs/{fullchain.pem,privkey.pem}` (Let's Encrypt or your CA).

`/docs` and `/openapi.json` are automatically disabled when
`APP_ENV=production` (`app/main.py`).

## 3. Observability

- **Sentry**: set `SENTRY_DSN`; `setup_sentry()` initialises it at startup
  (PII capture off). SDK ships via the image's `[observability]` extra.
- **Prometheus**: scrape `GET /metrics` (`http_requests_total`,
  `http_request_duration_seconds`, labelled by route *template* to bound
  cardinality). Point Grafana at it for latency/error dashboards.

## 4. Backup & restore

```bash
# Nightly (cron): pg_dump custom format + MinIO mirror + retention.
./scripts/backup.sh
# Restore a dump (asks for confirmation; drops/recreates objects).
./scripts/restore.sh ./backups/db/hrm_YYYYMMDD_HHMMSS.dump
```

A backup you have never restored is not a backup — schedule a **monthly test
restore** into a scratch database and verify `alembic current`.

## 5. Capacity / load

See `loadtest/README.md`: `seed_payroll.py` benchmarks a 10k-employee run;
`locustfile.py` drives interactive API load. Scale `worker` replicas on the
`payroll` queue and keep pgbouncer in front of Postgres.

## Bring it up

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
