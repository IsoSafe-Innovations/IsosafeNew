locals {
  name_prefix       = "${var.project}-${var.environment}"
  availability_zone = var.availability_zone != "" ? var.availability_zone : "${var.region}b"
  full_domain       = "${var.subdomain}.${var.domain_root}"
  key_name          = var.ssh_public_key != "" ? aws_key_pair.demo[0].key_name : var.key_name

  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}