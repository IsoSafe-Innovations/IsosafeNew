# AWS deployment: EC2 + private S3

This provisions a single Ubuntu 24.04 x86-64 server running nginx, the dashboard,
FastAPI, PostgreSQL/TimescaleDB and Redis. Camera inference runs on a separate
on-site agent with outbound HTTPS access to this server. MinIO is disabled.
This is a demo/staging architecture, not a highly available production setup.

## 1. Prerequisites

- AWS CLI authenticated to the intended account; verify with
  `aws sts get-caller-identity`.
- Terraform 1.9.8 (the version used by validation CI).
- An SSH key and your current public IPv4 address.
- A public Route 53 hosted zone for your domain, with the domain's authoritative
  nameservers pointing to that zone. An existing domain can be used.
- AWS permissions to manage the VPC, EC2, IAM, S3, Route 53 and Budgets resources
  declared in `infra/demo/`. No AWS credentials are embedded in the code.

### Windows: `aws login` and Terraform

The AWS CLI `login` session is not picked up by Terraform directly. After
`aws login --profile isosafe`, add a bridge profile to `~/.aws/config` (adjust
the path to `aws.exe` if needed):

```ini
[profile isosafe-terraform]
region = us-east-1
credential_process = C:\Users\admin\AppData\Local\Programs\Amazon\AWSCLIV2\aws.exe configure export-credentials --profile isosafe --format process
```

From the repo root, run plan/apply through the helper (same PowerShell window
where you ran `aws login`):

```powershell
.\deploy\terraform-aws-login.ps1 plan -out aws.tfplan
.\deploy\terraform-aws-login.ps1 apply aws.tfplan
.\deploy\terraform-aws-login.ps1 output -raw public_ip
```

Use **`-out aws.tfplan`** (two words). PowerShell treats `-out=aws.tfplan` as its own flag and Terraform sees extra arguments.

### External DNS (Whogohost)

For `demo.isosafe.com.ng` with DNS kept at Whogohost, set these in `infra/demo/terraform.tfvars`:

```hcl
region            = "us-east-1"
manage_route53_dns = false
domain_root       = "isosafe.com.ng"
subdomain         = "demo"
```

In this mode no Route 53 hosted zone or DNS permissions are required. After applying Terraform, run `terraform output -raw public_ip` and create an A record at Whogohost with name `demo` and that IP as its value (TTL 300). Keep the existing website, nameservers and email records. Confirm `demo.isosafe.com.ng` resolves to the Elastic IP before running `first_deploy.sh`; use `DOMAIN=demo.isosafe.com.ng` and `S3_REGION=us-east-1` in that command. The installer configures Let's Encrypt HTTPS.

## 2. Configure and provision infrastructure

From PowerShell in the repository root:

```powershell
Set-Location infra/demo
Copy-Item terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`. Replace every placeholder, including the SSH public key
and allowed IPs. Example:

```hcl
region            = "eu-west-1"
ssh_public_key    = "ssh-ed25519 REPLACE_WITH_YOUR_PUBLIC_KEY"
ssh_allowed_cidrs = ["YOUR_PUBLIC_IPV4/32"]
domain_root       = "yourdomain.com"
subdomain         = "demo"
bucket_name       = "isosafe-demo-snapshots-REPLACE_WITH_UNIQUE_SUFFIX"
instance_type     = "t3.medium"
root_volume_size  = 50
enable_bucket_versioning = true
termination_protection   = true
budget_limit_usd   = 100
budget_alert_email = "you@yourdomain.com"
operations_alert_email = "you@yourdomain.com"
```

Alternatively, leave `ssh_public_key` empty and set `key_name` to an EC2 key pair
already present in the chosen region. Never supply a private key to Terraform.
The instance and disk sizes above are starting points, not measured capacity.
Budget alerts do not impose a spending cap.

```powershell
terraform init
terraform fmt -check -recursive
terraform validate
terraform test
terraform plan -out=aws.tfplan
# Review the plan: the next command creates billable AWS resources.
terraform apply aws.tfplan
terraform output
```

Keep Terraform state and plan files private; do not commit them. Preserve the
state for subsequent updates, and use a secured remote backend for team work.
The provider lock file is committed so CI and operators use the same version.

Inbound ports are 80/443 for the public app and 22 for your allowed IPs only.
PostgreSQL, Redis and the API container are not published on public host ports.
IMDSv2 is required with hop limit 2 so containers can obtain the instance role's
S3 credentials. Do not add static S3 access keys.

## 3. Upload the prepared code

Choose one path. The local preparation changes must reach EC2 before deployment.

### A. Deploy this local checkout before it is pushed

From PowerShell in the repository root, create a source archive excluding local
secrets, Windows certificate bundles, local-only startup files and Terraform
state. The archive is written outside the checkout:

```powershell
$archive = Join-Path $env:TEMP 'isosafe-aws-source.tar.gz'
tar -czf $archive --exclude=.git --exclude=.env --exclude=.terraform --exclude='*.tfstate*' --exclude='*.tfvars' --exclude='*.tfplan' --exclude=node_modules --exclude=.venv --exclude=local-ca.crt --exclude=Dockerfile.local --exclude=docker-compose.local.yml --exclude=nginx.local.conf --exclude=Start-Local.ps1 --exclude=deploy/certs --exclude=deploy/backups -C . .
scp -i "$HOME/.ssh/id_ed25519" $archive ubuntu@YOUR_EC2_PUBLIC_IP:/tmp/isosafe-aws-source.tar.gz
ssh -i "$HOME/.ssh/id_ed25519" ubuntu@YOUR_EC2_PUBLIC_IP
```

On EC2:

```bash
sudo cloud-init status --wait
sudo docker compose version
sudo mkdir -p /opt/isosafe/app
sudo tar -xzf /tmp/isosafe-aws-source.tar.gz -C /opt/isosafe/app
cd /opt/isosafe/app
sudo env SKIP_CODE_UPDATE=1 \
  DOMAIN=demo.yourdomain.com ACME_EMAIL=you@yourdomain.com \
  S3_REGION=eu-west-1 S3_BUCKET=YOUR_TERRAFORM_BUCKET_NAME \
  BACKUP_BUCKET=YOUR_TERRAFORM_BACKUP_BUCKET \
  AWS_LOG_GROUP=/isosafe/demo/application OPS_LOG_GROUP=/isosafe/demo/operations \
  BOOTSTRAP_ADMIN_EMAIL=you@yourdomain.com \
  bash deploy/first_deploy.sh
```

### B. Deploy a committed version from GitHub

Commit and push the preparation changes first. On EC2, clone the repository to
`/opt/isosafe/app`, fetch and check out the branch or commit containing them, then
run its script with `REPO_REF` set to that branch or commit:

```bash
sudo cloud-init status --wait
sudo git clone --no-checkout https://github.com/IsoSafe-Innovations/IsosafeNew.git /opt/isosafe/app
sudo git -C /opt/isosafe/app fetch origin YOUR_DEPLOY_REF
sudo git -C /opt/isosafe/app checkout --detach FETCH_HEAD
cd /opt/isosafe/app
sudo env REPO_REF=YOUR_DEPLOY_REF \
  DOMAIN=demo.yourdomain.com ACME_EMAIL=you@yourdomain.com \
  S3_REGION=eu-west-1 S3_BUCKET=YOUR_TERRAFORM_BUCKET_NAME \
  BACKUP_BUCKET=YOUR_TERRAFORM_BACKUP_BUCKET \
  AWS_LOG_GROUP=/isosafe/demo/application OPS_LOG_GROUP=/isosafe/demo/operations \
  BOOTSTRAP_ADMIN_EMAIL=you@yourdomain.com \
  bash deploy/first_deploy.sh
```

The script supports branches, commit SHAs and `refs/pull/1/head`. Use a ref that
actually contains the deployment fixes. Authenticate Git separately if the
repository is private; do not embed credentials in its URL.

## 4. First deployment and checks

Before running the script, confirm `demo.yourdomain.com` resolves to Terraform's
Elastic IP. Let's Encrypt HTTP validation needs public port 80 and correct DNS.
The script builds the cloud images, runs migrations, creates a root-only `.env`
with generated secrets, installs HTTPS and automatic certificate renewal, then
checks database/Redis health and S3 role access. It prints the initial admin
password. Keep those credentials private. Existing `.env` files are preserved.

```bash
curl -fsS https://demo.yourdomain.com/api/health
# Expect status=ok, database.ok=true and redis.ok=true.
sudo systemctl status isosafe-certbot-renew.timer
cd /opt/isosafe/app
sudo docker compose -f docker-compose.yml -f docker-compose.cloud.yml -f docker-compose.aws.yml ps
sudo docker compose -f docker-compose.yml -f docker-compose.cloud.yml -f docker-compose.aws.yml logs --tail=100 backend nginx
```

Open `https://demo.yourdomain.com`, sign in and check the dashboard. Follow
[`agent/README.md`](agent/README.md) to install the site agent. Use the same
`AGENT_TOKEN` stored in the cloud `.env`; do not publish it. An offline agent is
expected until installed. Add a camera reachable by the agent and verify live
frames, heartbeats and an incident before calling the deployment accepted.

## 5. Operations and limits

- The deployment script installs six-hourly off-site backups, daily isolated
  restore drills and one-minute monitoring. Use the backup and log-group names
  from Terraform outputs, and confirm the SNS subscription email. Follow
  [`OPERATIONS.md`](OPERATIONS.md) for monitoring, recovery and release gates.
- Never delete `.env` to rotate database credentials on an existing database.
  Changing only `POSTGRES_PASSWORD` does not change PostgreSQL's stored password.
  Preserve the JWT, camera-encryption and agent secrets across deployments.
- Terraform refuses automatic deletion of a nonempty snapshot bucket. Disable
  EC2 termination protection deliberately before an intentional teardown.
- An existing VM's `user_data_replace_on_change=false` means bootstrap edits do
  not automatically rerun cloud-init. Inspect a Terraform plan before replacing
  an existing instance, and back up its Docker data first.
- The existing GitHub SSH deployment workflow needs separate setup: registry
  image access, a runner whose IP is allowed to SSH, and a deployment user with
  permissions for the root-owned checkout and `.env`. Use the manual procedure
  above until that setup is verified. This preparation does not enable it.
- Troubleshoot bootstrap with `/var/log/cloud-init-output.log`; troubleshoot S3
  with the bucket region, instance profile and metadata hop limit. Keep TLS
  verification enabled when diagnosing dependency or HTTPS errors.

Reference: [Canonical's Ubuntu AMI naming](https://ubuntu.com/aws/docs/aws-how-to/instances/find-ubuntu-images/)
and [AWS container metadata settings](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-IMDS-new-instances.html).
