# AWS preparation verification — 2026-10-27

## Verified locally

### Follow-up review (2026-10-27)

- Recreated local Nginx to apply the shared configuration mount; the previous
  running container failed `nginx -t` because the include directory was absent.
  Both local and cloud Nginx configurations now pass validation.
- Current source: backend lint passed; 141 tests passed and 1 skipped in an
  isolated container. Frontend locked install, production build and lint passed;
  npm audit reported zero vulnerabilities. Removed one unused frontend import.
- Terraform validation and all three mocked tests passed. AWS Compose retains
  private backend/database/cache ports and uses role credentials. Deployment
  shell syntax checks passed.
- All 14 cloud HTTPS/security probes passed with the local test certificate.
  No public AWS endpoint was used.
- Deployment workflow health verification now checks overall `status == "ok"`.
  Healthy, degraded and missing-status response cases were exercised.
- The running backend was stale. Refreshed the local backend/inference image
  with current source and Pillow 13.0.0, filelock 4.2.4, pip 26.2.2 and
  setuptools 84.2.1; `pip check` passed. The full clean Docker build was stopped
  during slow dependency downloads; this refresh reused existing dependencies
  and is not evidence of a completed clean production build. The test suite
  above ran before this image refresh; runtime checks followed the refresh.
- After the image refresh, health reported database and Redis healthy. The
  authenticated read-only probe passed 150 requests with zero errors,
  p95 42.44 ms, 10.05 requests/sec and 20 idle WebSocket connections over 15 seconds.
- Current checkout also contains pre-existing uncommitted Nginx/Compose edits
  and document deletions. This review did not publish or revert those changes.

### Earlier verification

- Backend tests: **141 passed, 1 skipped**, after the Python security updates.
- Backup helpers: tests reject corrupted S3 downloads, invalid upload checksums,
  and symlink database archive entries; recovery extraction leaves secrets alone.
- Recovery: a real dump of the local PostgreSQL 16 application database restored
  into a separate temporary database. Schema revision `0002`, 1 user, 0 cameras,
  and 0 incidents were readable. The temporary database was removed. See
  `recovery-local.json`. This is not a full-size dataset or a TimescaleDB test.
- Read-only local capacity test: **600 requests, 0 errors, p95 41.68 ms,
  10.01 requests/sec, 20 idle WebSocket connections**, approximately 60 seconds.
  See `capacity-local.json`. The database had no cameras or incidents.
- Cloud nginx tested over HTTPS with a trusted temporary test certificate:
  unauthenticated/forged-token reads rejected, metrics/media inaccessible,
  HTTPS redirect, HSTS, MIME protection and frame protection present. See
  `security-local.json`. Certificate verification remained enabled.
- Frontend built successfully with React Router 7.18.4 and Vite 8.3.5.
- npm audit (including build dependencies): **0 known vulnerabilities** after
  compatible transitive updates and the router/build-tool upgrades.
- Python installed-package audit: **0 known vulnerabilities** after updating
  Pillow, filelock, pip and setuptools to the patched versions recorded in
  `python-audit.json`. The audit included verification tools as well as runtime
  dependencies; production builds enforce the corresponding minimum versions.
  The general audit skips PyTorch CPU wheel suffixes. A separate normalized
  version check of torch 2.14.1 and torchvision 0.29.1 also found zero known
  vulnerabilities (`torch-audit.json`); this does not independently verify the
  binary provenance of the upstream CPU wheels.
- AWS Compose configuration: only backend/frontend/nginx/PostgreSQL/Redis active;
  data/API ports private; static S3 keys empty; application logs use CloudWatch.
- Terraform and deployment-script validation results are recorded by the local
  checks and the `Validate AWS deployment` CI workflow. Terraform tests use a
  mocked AWS provider and create no real resources.

## Still required on AWS

1. Apply a reviewed Terraform plan and deploy the prepared checkout.
2. Confirm the SNS email subscription and test an actual notification.
3. Let installation complete its initial S3 backup and off-site recovery drill;
   verify the CloudWatch logs/metrics/alarms and certificate-renewal timer.
4. Run `scripts.security_check` against the real public domain.
5. Run the staging capacity gate with representative data and the chosen EC2
   size, followed by an agent/video/incident soak on the intended camera hardware.
6. Exercise replacement-server recovery and measure actual RPO/RTO.

No claim of production capacity, high availability, penetration-test coverage,
OS/container vulnerability coverage, multi-tenant isolation or AWS account-wide
security is made. This remains a single-server deployment. Read-only load tests
do not measure live video, inference or incident-fanout throughput. Dependency
audits are point-in-time checks and run again in CI.
