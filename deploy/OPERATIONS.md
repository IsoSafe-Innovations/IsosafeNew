# AWS operations and recovery

## Enable and accept the installation

Set `operations_alert_email` in `infra/demo/terraform.tfvars`, apply the reviewed
Terraform plan, and confirm the SNS subscription email. Without that confirmation
the alarms exist but email delivery is not active. CloudWatch and S3 incur costs.

Use these additional Terraform outputs in **both** first-deployment commands in
`AWS.md`:

```bash
BACKUP_BUCKET=<terraform output -raw backup_bucket>
AWS_LOG_GROUP=<terraform output -raw application_log_group>
OPS_LOG_GROUP=<terraform output -raw operations_log_group>
```

These are environment variable values, not shell commands containing angle brackets.
For example, the application log group will usually be `/isosafe/demo/application`.
`first_deploy.sh` persists them in the root-only `.env`, installs systemd timers,
and runs an initial backup, off-site restore drill, and monitoring report. It fails
if those initial jobs fail. Redeploy the backend image when changing helpers.

## Backup policy

- Every six hours at 00:20, 06:20, 12:20, 18:20 **UTC** (01:20, 07:20, 13:20,
  19:20 Lagos time): a PostgreSQL custom-format dump plus `runtime.env` and a
  timestamp manifest are bundled and uploaded to a separate private S3 bucket.
- Every object is encrypted with S3 AES256 encryption. Bucket versioning and a
  35-day lifecycle are configured; local bundles are retained for seven days.
- The upload is verified by size and SHA-256 metadata before recording success.
  A download must match that checksum before it can be used for a recovery drill.
- The instance role can upload/read backups but cannot delete them. This is not
  S3 Object Lock: an AWS administrator can still alter retention or delete data.
- The bundle includes database passwords, JWT, camera-encryption and agent keys.
  Limit bucket access to recovery operators. Keep an additional encrypted copy
  of essential credentials and Terraform state in an independently managed vault.
  PostgreSQL dumps do not back up cluster-wide roles, Terraform state or code.
- Incident images stay in the separate snapshots bucket. Enable its versioning
  as shown in `AWS.md`; database backups do not contain camera video or S3 images.
- Target RPO is six hours plus job duration when backups are succeeding. This is
  not point-in-time recovery. Backups and monitoring are not enabled on AWS until
  the Terraform resources and installation script actually run there.

## Monitoring and alarms

Every minute the host publishes application and public HTTPS health, memory/disk
usage, backup/restore age, and TLS certificate expiry into `IsoSafe/Operations`,
dimensioned by `InstanceId`. It also writes a sanitized health summary to the
operations log group. Docker service logs go to the application group with 30-day
retention and bounded, nonblocking buffers. Queries are excluded from nginx
access logs because WebSocket authentication uses a query token.

| Signal | Alarm condition |
| --- | --- |
| Internal application / public HTTPS | Unhealthy for 3 minutes |
| Disk / memory | Above 80% / 85% for 5 minutes |
| Off-site backup | Last successful upload older than 7 hours |
| Restore check | Last successful drill older than 26 hours |
| TLS certificate | Expires in fewer than 14 days |
| EC2 status check | Failed for 2 minutes |
| EC2 CPU | Above 85% over two 5-minute periods |

Missing telemetry alarms as well, including when the backend or host cannot
publish. An initial startup grace period is not configured; new installations
can alarm until they have reported successfully. Confirm delivery with a
controlled test alarm in AWS, then reset it. This has not been tested in your
AWS account. Systemd journal records failures that occur before logs can upload.

```bash
sudo systemctl list-timers 'isosafe-*'
sudo journalctl -u isosafe-backup -u isosafe-restore-check -u isosafe-monitor --since today
sudo systemctl start isosafe-backup.service
sudo systemctl start isosafe-restore-check.service
sudo systemctl start isosafe-monitor.service
```

Backup and restore jobs serialize using `flock`; monitoring runs independently.
If a backup fails, inspect its journal and S3/IAM permissions, available disk,
and PostgreSQL health. Do not reset success timestamps to silence an alarm.

## Daily recovery drill

At 03:20 UTC (04:20 Lagos), the job downloads the latest **off-site** backup,
verifies its checksum, extracts only `database.dump`, creates a separate database
named `isosafe_restorecheck_<timestamp>`, and restores with `--exit-on-error`.
It uses TimescaleDB pre/post-restore hooks when available and checks the Alembic
revision plus users/cameras/incidents tables before recording success.
The temporary database is removed on exit. It never replaces the application DB.
The drill consumes disk and database resources: monitor its impact as data grows.

## Disaster recovery to a replacement server

Use a fresh server and empty database volume. Keep the old server and volumes
until acceptance is complete. Have an AWS recovery operator perform these steps:

1. Preserve/recover Terraform state, the source revision and access to the backup
   and snapshot buckets. Inspect the infrastructure plan; do not recreate or
   delete existing buckets unintentionally. Attach the correct instance role.
2. Provision the replacement host using Terraform. Wait for cloud-init and upload
   the prepared source. The recovery host must have access to the original backup
   bucket; update its IAM policy if deploying a separately named environment.
3. Select the desired backup object and record its timestamp. Download using an
   authenticated AWS tool or build the helper image **without starting services**:

   ```bash
   cd /opt/isosafe/app
   sudo install -d -m 700 /root/isosafe-recovery
   sudo docker build -t isosafe-recovery-tools backend
   sudo docker run --rm -e S3_REGION=YOUR_REGION -e BACKUP_BUCKET=ORIGINAL_BACKUP_BUCKET \
     -v /root/isosafe-recovery:/recovery isosafe-recovery-tools \
     python -m scripts.aws_ops download backups/YOUR_BACKUP.tar.gz /recovery/backup.tar.gz
   ```

4. Extract `runtime.env` and `database.dump` from this checksum-verified,
   administrator-selected bundle into `/root/isosafe-recovery`. Install
   `runtime.env` as `/opt/isosafe/app/.env` with owner root and mode 600. Preserve
   the camera-encryption key and database credentials. Update only infrastructure
   values (bucket names, log groups, region, CORS domain) if they changed.
5. Define a convenience command and start **only** the data services:

   ```bash
   dc() { sudo docker compose -f docker-compose.yml -f docker-compose.cloud.yml -f docker-compose.aws.yml "$@"; }
   dc up -d postgres redis
   ```

6. Wait for PostgreSQL to be healthy. Confirm this is a fresh database with no
   application tables before restoring. On the supplied TimescaleDB image:

   ```bash
   dc exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION IF NOT EXISTS timescaledb; SELECT timescaledb_pre_restore();"'
   dc exec -T postgres sh -c 'pg_restore --exit-on-error --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < /root/isosafe-recovery/database.dump
   dc exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT timescaledb_post_restore();"'
   ```

   Run these redirections from a root shell (`sudo -i`) because the recovery
   directory is root-only. Stop immediately on any error. Never use these commands
   against the running application's populated database.
7. Point DNS/Elastic IP at the replacement, then run `first_deploy.sh` with the
   existing `.env` and required deployment variables. It runs pending migrations,
   obtains HTTPS certificates, starts services and reinstalls operational jobs.
8. Sign in, compare users/cameras/incidents with the backup's expected history,
   verify S3 snapshots, decrypt/access a saved camera, reconnect the site agent,
   and exercise a real incident end to end. Record actual recovery duration and
   data loss. Retain the original server until the owner accepts the result.

An initial recovery-time target is 60 minutes after infrastructure and source are
available. It is **unverified on AWS**; image builds, DNS, dataset size and network
speed can exceed it. Measure it during an AWS recovery exercise before promising it.

## Security and capacity release gates

From a separate machine against the deployed staging URL:

```bash
cd backend
python -m scripts.security_check --base https://demo.yourdomain.com
export CAPACITY_EMAIL=YOUR_TEST_OPERATOR_EMAIL
read -s -p 'Test operator password: ' CAPACITY_PASSWORD; export CAPACITY_PASSWORD; echo
python -m scripts.capacity_check --base https://demo.yourdomain.com \
  --seconds 1800 --rps 50 --concurrency 20 --ws-clients 20 \
  --max-p95-ms 500 --max-error-rate 0.01 --output capacity-aws.json
unset CAPACITY_PASSWORD
```

The capacity gate fails if p95 exceeds 500 ms, errors exceed 1%, WebSockets close,
or achieved RPS falls below 90% of target. It is read-only and does not create test
cameras. Seed representative staging data first. It tests API and idle WebSockets,
not incident fanout, live video throughput, or agent inference. Test those with
real cameras on the intended on-site hardware, and monitor CPU/memory/disk,
database connections, agent FPS and alert latency during a longer soak.

Local results and audit scopes are recorded in `reports/VERIFICATION.md`.
Re-run package audits and the frontend build in CI. Local results do not certify
an AWS account, network, operating system image, tenant isolation or camera fleet.
