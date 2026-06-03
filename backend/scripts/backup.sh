#!/usr/bin/env bash
# ============================================================================
# Backup PostgreSQL (custom format) + mirror the MinIO/S3 bucket.
# Designed to run from cron on the host or in a sidecar container.
#
#   ./scripts/backup.sh
#
# Env (override as needed):
#   PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE   - Postgres connection
#   BACKUP_DIR        - where to write dumps (default ./backups)
#   RETENTION_DAYS    - delete dumps older than this (default 14)
#   S3_ALIAS          - mc alias for object storage (optional; needs `mc`)
#   S3_BUCKET         - bucket to mirror (default hrm)
# ============================================================================
set -euo pipefail

PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-hrm}"
PGDATABASE="${PGDATABASE:-hrm}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
S3_BUCKET="${S3_BUCKET:-hrm}"

STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "${BACKUP_DIR}/db" "${BACKUP_DIR}/objects"

DB_FILE="${BACKUP_DIR}/db/hrm_${STAMP}.dump"
echo "==> pg_dump -> ${DB_FILE}"
# Custom format (-Fc) = compressed + selective restore via pg_restore.
PGPASSWORD="${PGPASSWORD:-}" pg_dump \
  -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" \
  -Fc -f "${DB_FILE}"

# Integrity check: list the archive TOC (fails if the dump is corrupt).
pg_restore --list "${DB_FILE}" > /dev/null
echo "    dump OK ($(du -h "${DB_FILE}" | cut -f1))"

# Mirror object storage (payslip PDFs etc.) if an mc alias is configured.
if [[ -n "${S3_ALIAS:-}" ]] && command -v mc > /dev/null; then
  echo "==> mirror ${S3_ALIAS}/${S3_BUCKET} -> ${BACKUP_DIR}/objects/${STAMP}"
  mc mirror --quiet "${S3_ALIAS}/${S3_BUCKET}" "${BACKUP_DIR}/objects/${STAMP}"
fi

# Retention: prune dumps older than RETENTION_DAYS.
echo "==> prune dumps older than ${RETENTION_DAYS} days"
find "${BACKUP_DIR}/db" -name 'hrm_*.dump' -mtime "+${RETENTION_DAYS}" -delete

echo "Backup done: ${STAMP}"
