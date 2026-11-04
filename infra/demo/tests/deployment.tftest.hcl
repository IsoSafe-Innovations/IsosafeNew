# Offline mocked tests: no AWS credentials or real resources (Terraform >= 1.7).
mock_provider "aws" {
  mock_resource "aws_iam_policy" {
    defaults = { arn = "arn:aws:iam::123456789012:policy/offline-policy" }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:us-east-1:123456789012:offline-operations" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::isosafe-offline-validation" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:us-east-1:123456789012:log-group:/offline" }
  }
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
      arn        = "arn:aws:iam::123456789012:user/offline-test"
    }
  }
  mock_data "aws_ami" {
    defaults = {
      id = "ami-0123456789abcdef0"
    }
  }
  mock_resource "aws_eip" {
    defaults = {
      public_ip = "203.0.113.20"
    }
  }
}

variables {
  key_name               = "test-key"
  ssh_allowed_cidrs      = ["203.0.113.10/32"]
  domain_root            = "example.com"
  hosted_zone_id         = "Z0123456789EXAMPLE"
  bucket_name            = "isosafe-offline-validation"
  termination_protection = true
  operations_alert_email = "ops@example.com"
}

run "cloud_bootstrap_and_storage" {
  command = apply

  assert {
    condition     = aws_s3_bucket_public_access_block.backups.block_public_policy && aws_s3_bucket_public_access_block.backups.block_public_acls && aws_s3_bucket_versioning.backups.versioning_configuration[0].status == "Enabled" && !aws_s3_bucket.backups.force_destroy
    error_message = "Recovery backups require private, versioned storage protected from automatic deletion."
  }
  assert {
    condition     = !strcontains(aws_iam_role_policy.operations.policy, "s3:DeleteObject")
    error_message = "The VM must not have permission to delete its off-site backups."
  }
  assert {
    condition     = aws_cloudwatch_metric_alarm.operations["BackupAgeHours"].treat_missing_data == "breaching" && aws_cloudwatch_metric_alarm.operations["RestoreCheckAgeHours"].treat_missing_data == "breaching" && aws_cloudwatch_metric_alarm.operations["PublicHTTPSHealthy"].treat_missing_data == "breaching"
    error_message = "Missing health, backup or recovery telemetry must trigger alarms."
  }

  assert {
    condition     = aws_instance.demo.disable_api_termination
    error_message = "The termination protection setting must be applied to EC2."
  }
  assert {
    condition     = startswith(aws_instance.demo.user_data, "#!/usr/bin/env bash\n")
    error_message = "EC2 user_data must be an executable shell script, not base64 text."
  }
  assert {
    condition     = aws_instance.demo.metadata_options[0].http_tokens == "required" && aws_instance.demo.metadata_options[0].http_put_response_hop_limit == 2
    error_message = "Containers need IMDSv2 with a response hop limit of 2 for S3 role credentials."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.snapshots.block_public_acls && aws_s3_bucket_public_access_block.snapshots.block_public_policy && aws_s3_bucket_public_access_block.snapshots.ignore_public_acls && aws_s3_bucket_public_access_block.snapshots.restrict_public_buckets
    error_message = "Incident snapshots must remain private."
  }
}

run "external_dns" {
  command = plan
  variables {
    manage_route53_dns = false
    hosted_zone_id     = ""
  }
  assert {
    condition     = length(data.aws_route53_zone.demo) == 0 && length(aws_route53_record.demo) == 0
    error_message = "External DNS must not look up a Route53 zone or create a DNS record."
  }
}

run "reject_public_ssh" {
  command = plan
  variables {
    ssh_allowed_cidrs = ["0.0.0.0/0"]
  }
  expect_failures = [var.ssh_allowed_cidrs]
}

run "reject_invalid_ssh_cidr" {
  command = plan
  variables {
    ssh_allowed_cidrs = ["not-a-cidr"]
  }
  expect_failures = [var.ssh_allowed_cidrs]
}
