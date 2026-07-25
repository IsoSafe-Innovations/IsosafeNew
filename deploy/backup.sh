#!/bin/sh
# Nightly pg_dump with 14-day rotation. Runs as the `backup` compose service.
# Restore procedure: see deploy/RESTORE.md
set -eu

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

while true; do
  NOW=$(date +%s)
  # next 02:30 UTC
  TARGET=$(date -d "tomorrow 02:30" +%s 2>/dev/null || date -v+1d -j -f "%H:%M" "02:30" +%s)
  SLEEP=$((TARGET - NOW))
  [ "$SLEEP" -lt 60 ] && SLEEP=86400
  echo "backup: sleeping ${SLEEP}s until next run"
  sleep "$SLEEP"

  STAMP=$(date +%Y%m%d_%H%M%S)
  FILE="/backups/isosafe_${STAMP}.dump"
  echo "backup: dumping to $FILE"
  if pg_dump -Fc -f "$FILE"; then
    echo "backup: done ($(du -h "$FILE" | cut -f1))"
  else
    echo "backup: FAILED" >&2
    rm -f "$FILE"
  fi

  find /backups -name 'isosafe_*.dump' -mtime "+${RETENTION_DAYS}" -delete
done
