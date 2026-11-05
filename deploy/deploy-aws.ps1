# Deploy local changes to the AWS demo VM from Windows PowerShell.
#
#   .\deploy\deploy-aws.ps1                       # commit + push + update server
#   .\deploy\deploy-aws.ps1 -Message "New logos"  # custom commit message
#   .\deploy\deploy-aws.ps1 -SkipPush             # server only (already pushed)
#
# Prerequisites: SSH to the VM works from this PC (your IP is in ssh_allowed_cidrs),
# and the VM already ran deploy/first_deploy.sh once. Secrets (.env) live on the
# VM only and are never touched.
param(
    [string]$Message = "Update Iso Safe",
    [switch]$SkipPush,
    [string]$Remote = "isosafe-innovations",
    [string]$Branch = "main",
    [string]$Server = "ubuntu@52.6.30.165",
    [string]$Key = "$HOME\.ssh\id_ed25519",
    [string]$Domain = "demo.isosafe.com.ng"
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# --- 1. Commit and push ------------------------------------------------------
if (-not $SkipPush) {
    if (-not (git config user.email)) {
        git config user.email "tech@isosafe.com.ng"
        git config user.name "Iso Safe Innovations"
    }
    git add -A
    if (git status --porcelain) {
        git commit -m $Message
    } else {
        Write-Host "Nothing new to commit."
    }
    git push $Remote $Branch
    if ($LASTEXITCODE -ne 0) { throw "git push failed (pull/rebase first if the remote has new commits)." }
}

# --- 2. Update the server ----------------------------------------------------
$remoteScript = @'
set -euo pipefail
cd /opt/isosafe/app
sudo git fetch --depth 1 origin __BRANCH__
sudo git reset --hard FETCH_HEAD
COMPOSE="sudo docker compose -f docker-compose.yml -f docker-compose.cloud.yml -f docker-compose.aws.yml"
$COMPOSE up -d --build
$COMPOSE restart nginx

# The agent runs from the same backend image: recreate it so it picks up new code.
if sudo docker ps -a --format '{{.Names}}' | grep -qx isosafe-agent; then
  TOKEN=$(sudo grep '^AGENT_TOKEN=' .env | cut -d= -f2)
  sudo docker rm -f isosafe-agent >/dev/null
  sudo docker run -d --name isosafe-agent --restart unless-stopped \
    -e AGENT_MODE=1 -e CLOUD_URL=https://__DOMAIN__ -e AGENT_TOKEN="$TOKEN" \
    -v isosafe-models:/data/models \
    -v /opt/isosafe/sample_videos:/data/sample_videos:ro \
    isosafe-backend:local python -m app.pipeline.runner >/dev/null
  echo "agent restarted"
fi
sudo docker image prune -f >/dev/null
sleep 10
curl -fsS https://__DOMAIN__/api/health && echo
'@
$remoteScript = $remoteScript.Replace('__BRANCH__', $Branch).Replace('__DOMAIN__', $Domain).Replace("`r", "")

Write-Host "Deploying to $Server ..."
$remoteScript | ssh -i $Key -o StrictHostKeyChecking=accept-new $Server "bash -s"
if ($LASTEXITCODE -ne 0) { throw "Remote deploy failed." }

Write-Host "`nDone: https://$Domain  (hard refresh with Ctrl+Shift+R)"
