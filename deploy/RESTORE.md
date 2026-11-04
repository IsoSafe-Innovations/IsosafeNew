# Database Restore Procedure

For AWS deployments, use [OPERATIONS.md](OPERATIONS.md). AWS backups contain both
the database dump and runtime encryption/authentication secrets in private S3;
the procedure below describes the older local-only backup service.

Backups are written nightly at 02:30 UTC by the `backup` service to the
`deploy/backups/` host directory as custom-format dumps
(`isosafe_YYYYMMDD_HHMMSS.dump`), rotated after 14 days.

## Restore steps

1. Stop the services that write to the database:

   ```bash
   docker compose stop backend inference
   ```

2. Drop and recreate the database, then restore:

   ```bash
   docker compose exec postgres dropdb -U isosafe --force isosafe
   docker compose exec postgres createdb -U isosafe isosafe
   docker compose exec postgres pg_restore -U isosafe -d isosafe /backups/isosafe_<STAMP>.dump
   ```

   TimescaleDB note: `pg_restore` into a fresh database requires the extension
   pre-loading step:

   ```bash
   docker compose exec postgres psql -U isosafe -d isosafe \
     -c "SELECT timescaledb_pre_restore();"
   docker compose exec postgres pg_restore -U isosafe -d isosafe /backups/isosafe_<STAMP>.dump
   docker compose exec postgres psql -U isosafe -d isosafe \
     -c "SELECT timescaledb_post_restore();"
   ```

3. Restart:

   ```bash
   docker compose start backend inference
   ```

4. Verify: `curl -k https://<host>/api/health` should report database `ok: true`,
   and the dashboard should show cameras and historical analytics.

Snapshots and heatmaps live on the `media` Docker volume and are not part of the
SQL dump; back that volume up separately if snapshot history matters.
