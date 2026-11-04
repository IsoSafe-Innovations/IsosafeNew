#!/usr/bin/env bash
# Host-side jobs; timers installed by install_operations.sh. No production restore.
set -euo pipefail
umask 077
. "${OPS_ENV_FILE:-/etc/isosafe/operations.env}"
cd "$APP_DIR"
compose() { docker compose -f docker-compose.yml -f docker-compose.cloud.yml -f docker-compose.aws.yml "$@"; }
helper() { compose exec -T backend python -m scripts.aws_ops "$@"; }
ROOT="$APP_DIR/deploy/backups"
mkdir -p "$ROOT/state"
if [[ "${1:-}" != monitor ]]; then
  exec 9>"$ROOT/operations.lock"
  flock -w 600 9 || { echo 'Another operations job is running'; exit 1; }
fi
WORK=""
CHECK_DB=""
cleanup() {
  if [[ "$CHECK_DB" =~ ^isosafe_restorecheck_[0-9]+$ ]]; then
    compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" --if-exists "$1"' sh "$CHECK_DB"
  fi
  [[ -z "$WORK" ]] || rm -rf -- "$WORK"
}
trap cleanup EXIT
require_disk_space() {
  local needed free
  needed=$(compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT pg_database_size(current_database())"')
  free=$(df -PB1 "$ROOT" | awk 'NR==2 {print $4}')
  (( free > needed * 2 + 1073741824 )) || { echo 'Insufficient free disk for a safe backup/recovery drill' >&2; exit 1; }
}

case "${1:?backup, restore-check or monitor}" in
  backup)
    require_disk_space
    WORK=$(mktemp -d "$ROOT/job.XXXXXX")
    compose exec -T postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$WORK/database.dump"
    compose exec -T postgres pg_restore --list < "$WORK/database.dump" > /dev/null
    install -m 600 .env "$WORK/runtime.env"
    printf '{"created_at":"%s","format":1}\n' "$(date -u +%FT%TZ)" > "$WORK/manifest.json"
    FILE="isosafe_$(date -u +%Y%m%dT%H%M%SZ)_$RANDOM.tar.gz"
    tar -czf "$ROOT/$FILE" -C "$WORK" database.dump runtime.env manifest.json
    helper upload "/data/backups/$FILE" > "$ROOT/state/latest-key.tmp"
    mv "$ROOT/state/latest-key.tmp" "$ROOT/state/latest-key"
    date +%s > "$ROOT/state/backup-success"
    find "$ROOT" -maxdepth 1 -name 'isosafe_*.tar.gz' -mtime +7 -delete
    echo 'Off-site database and runtime-secret backup verified'
    ;;
  restore-check)
    require_disk_space
    WORK=$(mktemp -d "$ROOT/job.XXXXXX")
    RELATIVE="${WORK#"$ROOT/"}"
    KEY=$(helper latest)
    helper download "$KEY" "/data/backups/$RELATIVE/backup.tar.gz"
    helper extract-db "/data/backups/$RELATIVE/backup.tar.gz" "/data/backups/$RELATIVE/database.dump"
    CHECK_DB="isosafe_restorecheck_$(date +%s)"
    compose exec -T postgres sh -c 'createdb -U "$POSTGRES_USER" -T template0 "$1"' sh "$CHECK_DB"
    HAS_TS=$(compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$1" -Atqc "SELECT count(*) FROM pg_available_extensions WHERE name = '\''timescaledb'\''"' sh "$CHECK_DB")
    if [[ "$HAS_TS" == 1 ]]; then
      compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -c "CREATE EXTENSION IF NOT EXISTS timescaledb; SELECT timescaledb_pre_restore();"' sh "$CHECK_DB"
    fi
    compose exec -T postgres sh -c 'pg_restore --exit-on-error --no-owner -U "$POSTGRES_USER" -d "$1"' sh "$CHECK_DB" < "$WORK/database.dump"
    if [[ "$HAS_TS" == 1 ]]; then
      compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -c "SELECT timescaledb_post_restore();"' sh "$CHECK_DB"
    fi
    compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -c "SELECT version_num FROM alembic_version; SELECT count(*) AS users FROM users; SELECT count(*) AS cameras FROM cameras; SELECT count(*) AS incidents FROM incidents;"' sh "$CHECK_DB"
    date +%s > "$ROOT/state/restore-success"
    echo 'Off-site recovery drill passed in isolated database'
    ;;
  monitor)
    DISK=$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
    MEMORY=$(awk '/MemTotal:/ {t=$2} /MemAvailable:/ {a=$2} END {print 100*(t-a)/t}' /proc/meminfo)
    helper monitor --domain "$DOMAIN" --instance-id "$INSTANCE_ID" --disk "$DISK" --memory "$MEMORY"
    ;;
  *) echo 'Unknown operations job' >&2; exit 2 ;;
esac
