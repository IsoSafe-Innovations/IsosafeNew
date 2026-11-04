# Run Terraform with credentials from `aws login` on Windows.
# Prerequisite: `aws login --profile isosafe` in this same shell.
# Profile isosafe-terraform in ~/.aws/config — see deploy/AWS.md.
#
# Usage (note: -out must be two tokens, not -out=file):
#   .\deploy\terraform-aws-login.ps1 plan -out aws.tfplan
#   .\deploy\terraform-aws-login.ps1 apply aws.tfplan
#   .\deploy\terraform-aws-login.ps1 output -raw public_ip
#
# Or stop PowerShell from parsing flags:  .\deploy\terraform-aws-login.ps1 -- plan -out aws.tfplan

$ErrorActionPreference = 'Stop'

if ($args.Count -eq 0) {
    throw @'
Pass Terraform arguments after the script name, e.g.:
  .\deploy\terraform-aws-login.ps1 plan -out aws.tfplan
  .\deploy\terraform-aws-login.ps1 apply aws.tfplan
'@
}

# Optional explicit "--" separator
if ($args[0] -eq '--') {
    $args = $args[1..($args.Count - 1)]
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$demoDir = Join-Path $repoRoot 'infra\demo'
$tf = if (Get-Command terraform -ErrorAction SilentlyContinue) {
    (Get-Command terraform).Source
} else {
    Join-Path $env:LOCALAPPDATA 'terraform\terraform.exe'
}
if (-not (Test-Path $tf)) {
    throw "Terraform not found. Install Terraform or use $env:LOCALAPPDATA\terraform\terraform.exe"
}

$env:AWS_PROFILE = 'isosafe-terraform'
Push-Location $demoDir
try {
    & $tf @args
} finally {
    Pop-Location
}
