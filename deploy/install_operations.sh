#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root' >&2; exit 1; }
APP_DIR="${APP_DIR:-/opt/isosafe/app}"
DOMAIN="${DOMAIN:?set DOMAIN}"
TOKEN=$(curl -fsS --max-time 10 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token)
INSTANCE_ID=$(curl -fsS --max-time 10 -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id)
install -d -m 700 /etc/isosafe "$APP_DIR/deploy/backups"
printf 'APP_DIR=%q\nDOMAIN=%q\nINSTANCE_ID=%q\n' "$APP_DIR" "$DOMAIN" "$INSTANCE_ID" > /etc/isosafe/operations.env
chmod 600 /etc/isosafe/operations.env
chmod +x "$APP_DIR/deploy/operations.sh"
for JOB in backup restore-check monitor; do
  case "$JOB" in
    backup) SCHEDULE='*-*-* 00,06,12,18:20:00' ;;
    restore-check) SCHEDULE='*-*-* 03:20:00' ;;
    monitor) SCHEDULE='*-*-* *:*:00' ;;
  esac
  cat > "/etc/systemd/system/isosafe-$JOB.service" <<EOF
[Unit]
Description=Iso Safe $JOB
Requires=docker.service
After=docker.service network-online.target
[Service]
Type=oneshot
UMask=0077
ExecStart=/bin/bash $APP_DIR/deploy/operations.sh $JOB
TimeoutStartSec=3600
EOF
  cat > "/etc/systemd/system/isosafe-$JOB.timer" <<EOF
[Unit]
Description=Schedule Iso Safe $JOB (UTC)
[Timer]
OnCalendar=$SCHEDULE UTC
Persistent=true
[Install]
WantedBy=timers.target
EOF
done
systemctl daemon-reload
systemctl enable --now isosafe-backup.timer isosafe-restore-check.timer isosafe-monitor.timer
# Initial jobs prove backups and recovery before installation is called successful.
systemctl start isosafe-backup.service
systemctl start isosafe-restore-check.service
systemctl start isosafe-monitor.service
