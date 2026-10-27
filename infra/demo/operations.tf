variable "operations_alert_email" {
  description = "Email for operational alarms; confirm the SNS subscription after apply."
  type        = string
  validation {
    condition     = can(regex("^[^@ ]+@[^@ ]+\\.[^@ ]+$", var.operations_alert_email))
    error_message = "Set operations_alert_email to a monitored email address."
  }
}

resource "aws_s3_bucket" "backups" {
  bucket_prefix = "${local.name_prefix}-backups-"
  force_destroy = false
}
resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket     = aws_s3_bucket.backups.id
  depends_on = [aws_s3_bucket_versioning.backups]
  rule {
    id     = "retain-35-days"
    status = "Enabled"
    filter { prefix = "backups/" }
    expiration { days = 35 }
    noncurrent_version_expiration { noncurrent_days = 35 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}
resource "aws_s3_bucket_policy" "backups" {
  bucket = aws_s3_bucket.backups.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Deny", Principal = "*", Action = "s3:*",
      Resource  = [aws_s3_bucket.backups.arn, "${aws_s3_bucket.backups.arn}/*"],
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_cloudwatch_log_group" "application" {
  name              = "/${var.project}/${var.environment}/application"
  retention_in_days = 30
}
resource "aws_cloudwatch_log_group" "operations" {
  name              = "/${var.project}/${var.environment}/operations"
  retention_in_days = 30
}
resource "aws_sns_topic" "operations" { name = "${local.name_prefix}-operations" }
resource "aws_sns_topic_subscription" "operations_email" {
  topic_arn = aws_sns_topic.operations.arn
  protocol  = "email"
  endpoint  = var.operations_alert_email
}
resource "aws_iam_role_policy" "operations" {
  name = "${local.name_prefix}-operations"
  role = aws_iam_role.demo.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.backups.arn },
      { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject", "s3:AbortMultipartUpload"], Resource = "${aws_s3_bucket.backups.arn}/backups/*" },
      { Effect = "Allow", Action = ["cloudwatch:PutMetricData"], Resource = "*", Condition = { StringEquals = { "cloudwatch:namespace" = "IsoSafe/Operations" } } },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["${aws_cloudwatch_log_group.application.arn}:*", "${aws_cloudwatch_log_group.operations.arn}:*"] }
    ]
  })
}

locals {
  operations_alarms = {
    ApplicationHealthy   = { threshold = 1, comparison = "LessThanThreshold", periods = 3 }
    PublicHTTPSHealthy   = { threshold = 1, comparison = "LessThanThreshold", periods = 3 }
    DiskUsedPercent      = { threshold = 80, comparison = "GreaterThanThreshold", periods = 5 }
    MemoryUsedPercent    = { threshold = 85, comparison = "GreaterThanThreshold", periods = 5 }
    BackupAgeHours       = { threshold = 7, comparison = "GreaterThanThreshold", periods = 3 }
    RestoreCheckAgeHours = { threshold = 26, comparison = "GreaterThanThreshold", periods = 3 }
    TLSExpiryDays        = { threshold = 14, comparison = "LessThanThreshold", periods = 3 }
  }
}
resource "aws_cloudwatch_metric_alarm" "operations" {
  for_each            = local.operations_alarms
  alarm_name          = "${local.name_prefix}-${each.key}"
  namespace           = "IsoSafe/Operations"
  metric_name         = each.key
  dimensions          = { InstanceId = aws_instance.demo.id }
  statistic           = "Average"
  period              = 60
  evaluation_periods  = each.value.periods
  threshold           = each.value.threshold
  comparison_operator = each.value.comparison
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  ok_actions          = [aws_sns_topic.operations.arn]
}
resource "aws_cloudwatch_metric_alarm" "cpu" {
  alarm_name          = "${local.name_prefix}-cpu"
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  dimensions          = { InstanceId = aws_instance.demo.id }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
}
resource "aws_cloudwatch_metric_alarm" "instance_status" {
  alarm_name          = "${local.name_prefix}-instance-status"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed"
  dimensions          = { InstanceId = aws_instance.demo.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
}
output "backup_bucket" { value = aws_s3_bucket.backups.id }
output "application_log_group" { value = aws_cloudwatch_log_group.application.name }
output "operations_log_group" { value = aws_cloudwatch_log_group.operations.name }
output "operations_topic_arn" { value = aws_sns_topic.operations.arn }
