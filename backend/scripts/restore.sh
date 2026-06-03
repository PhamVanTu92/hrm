#!/usr/bin/env bash
# ============================================================================
# Restore a PostgreSQL dump produced by backup.sh.
#
#   ./scripts/restore.sh ./backups/db/hrm_20260529_010000.dump
#
# DANGER: this drops and recreates objects in the target database. Never run
# against production without confirming the target. A periodic *test restore*
# into a scratch DB is the only way to know your backups actually work.
#
# Env: PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE
# ============================================================================
set -euo pipefail

DUMP_FILE="${1:?usage: restore.sh <dump-file>}"
PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-hrm}"
PGDATABASE="${PGDATABASE:-hrm}"

if [[ ! -f "${DUMP_FILE}" ]]; then
  echo "Dump not found: ${DUMP_FILE}" >&2
  exit 1
fi

echo "==> Restoring ${DUMP_FILE} into ${PGUSER}@${PGHOST}:${PGPORT}/${PGDATABASE}"
echo "    (clean + if-exists; existing objects will be replaced)"
read -r -p "Type the database name to confirm: " confirm
[[ "${confirm}" == "${PGDATABASE}" ]] || { echo "Aborted."; exit 1; }

PGPASSWORD="${PGPASSWORD:-}" pg_restore \
  -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" \
  --clean --if-exists --no-owner --no-privileges \
  "${DUMP_FILE}"

echo "Restore complete. Run 'alembic current' to verify the schema revision."
