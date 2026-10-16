# Re-creatable key pair from the owner's public key. Provide 'ssh_public_key'
# (recommended) or reuse an existing pair via 'key_name'.
resource "aws_key_pair" "demo" {
  count = var.ssh_public_key != "" ? 1 : 0

  key_name   = "${local.name_prefix}-vm"
  public_key = var.ssh_public_key
  tags       = { Name = "${local.name_prefix}-vm" }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Cloud-init: bootstrap Docker + Compose so the Day-6 manual deploy (or the
# Day-7 GitHub Actions SSH deploy) only needs to clone the repo and write the
# root-only .env before 'docker compose up'. No secrets live here.
locals {
  user_data = <<-EOT
    #!/usr/bin/env bash
    set -euo pipefail
    export DEBIAN_FRONTEND=noninteractive

    apt-get update -y
    apt-get install -y ca-certificates curl git gnupg

    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
    usermod -aG docker ubuntu

    mkdir -p /opt/isosafe/deploy/backups
    chown -R ubuntu:ubuntu /opt/isosafe
  EOT
}

resource "aws_instance" "demo" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.demo.id]
  key_name                    = local.key_name
  iam_instance_profile        = aws_iam_instance_profile.demo.name
  associate_public_ip_address = false
  user_data                   = base64encode(local.user_data)
  user_data_replace_on_change = false

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_size
    encrypted   = true
  }

  lifecycle {
    precondition {
      condition     = local.key_name != ""
      error_message = "Set either 'ssh_public_key' or 'key_name' so the VM can be reached for deploy and debugging."
    }
  }

  tags = { Name = "${local.name_prefix}-vm" }
}