variable "project" {
  description = "Project name, used as a resource tag/label prefix."
  type        = string
  default     = "isosafe"
}

variable "environment" {
  description = "Environment name, used as a resource tag/label prefix."
  type        = string
  default     = "demo"
}

variable "region" {
  description = "AWS region for the demo stack (DQ-01: closest to the demo audience)."
  type        = string
  default     = "us-east-1"
}

variable "availability_zone" {
  description = "Availability zone for the subnet. Defaults to the region's 'b' zone when empty."
  type        = string
  default     = ""
}

variable "vpc_cidr" {
  description = "CIDR block for the dedicated demo VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR block for the single public subnet."
  type        = string
  default     = "10.0.1.0/24"
}

variable "instance_type" {
  description = "EC2 instance type for the demo VM (Docker + Postgres + Redis + backend + frontend)."
  type        = string
  default     = "t3.medium"
}

variable "root_volume_size" {
  description = "Root EBS volume size in GiB."
  type        = number
  default     = 50
}

variable "ssh_public_key" {
  description = "Developer/owner public key; a dedicated AWS key pair is created from it. Leave empty to reuse an existing key via 'key_name'."
  type        = string
  default     = ""
}

variable "key_name" {
  description = "Existing AWS key pair name to use when 'ssh_public_key' is empty."
  type        = string
  default     = ""
}

variable "ssh_allowed_cidrs" {
  description = "IPv4 CIDRs allowed to SSH to the demo VM (owner/dev IPs only, per PRD DEMO-FR-60)."
  type        = list(string)
  default     = []

  validation {
    condition = length(var.ssh_allowed_cidrs) > 0 && alltrue([
      for cidr in var.ssh_allowed_cidrs :
      can(cidrnetmask(cidr)) && try(tonumber(split("/", cidr)[1]) > 0, false)
    ])
    error_message = "ssh_allowed_cidrs must contain valid restricted IPv4 CIDRs; 0.0.0.0/0 is not allowed."
  }
}

variable "domain_root" {
  description = "Root domain that hosts the demo record, e.g. 'isosafe.com'. Must exist in Route53 unless 'hosted_zone_id' is set."
  type        = string
}

variable "subdomain" {
  description = "Subdomain for the demo front door, e.g. 'demo' -> https://demo.<domain_root>."
  type        = string
  default     = "demo"
}

variable "hosted_zone_id" {
  description = "Optional Route53 hosted zone ID; otherwise the zone named by 'domain_root' is looked up."
  type        = string
  default     = ""
}

variable "bucket_name" {
  description = "Globally unique S3 bucket name for incident snapshots. Private, SSE-encrypted, public access blocked."
  type        = string
}

variable "enable_bucket_versioning" {
  description = "Enable S3 versioning on the snapshots bucket."
  type        = bool
  default     = false
}

variable "termination_protection" {
  description = "Enable EC2 termination protection."
  type        = bool
  default     = false
}

variable "budget_limit_usd" {
  description = "Monthly AWS cost budget in USD (PRD DEMO-FR-65)."
  type        = number
  default     = 100

  validation {
    condition     = var.budget_limit_usd > 0
    error_message = "budget_limit_usd must be greater than 0."
  }
}

variable "budget_alert_email" {
  description = "Email for budget alerts (80% actual, 100% forecasted). Empty disables email notifications."
  type        = string
  default     = ""
}
