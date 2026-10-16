output "demo_url" {
  description = "Public front door of the demo (Day-6 target)."
  value       = "https://${local.full_domain}"
}

output "instance_id" {
  description = "Demo VM instance id."
  value       = aws_instance.demo.id
}

output "public_ip" {
  description = "Elastic IP attached to the demo VM."
  value       = aws_eip.demo.public_ip
}

output "ssh_command" {
  description = "SSH access from an allowed developer IP."
  value       = "ssh -i <key> ubuntu@${aws_eip.demo.public_ip}"
}

output "snapshots_bucket" {
  description = "Private S3 bucket for incident snapshots."
  value       = aws_s3_bucket.snapshots.id
}

output "iam_role" {
  description = "VM instance profile / role."
  value       = aws_iam_instance_profile.demo.name
}

output "security_group_id" {
  description = "Security group applied to the demo VM (80/443 internet, 22 owner-only)."
  value       = aws_security_group.demo.id
}

output "budget_name" {
  description = "AWS monthly cost budget name (DEMO-FR-65)."
  value       = aws_budgets_budget.demo.name
}