# VM IAM role restricted to the demo snapshots bucket ONLY (PRD DEMO-FR-60:
# "IAM role for the VM with access to that bucket only"). No other AWS
# permissions are granted, so a compromised instance cannot reach other
# resources.

resource "aws_iam_role" "demo" {
  name        = "${local.name_prefix}-vm"
  description = "Iso Safe demo VM role: S3 access to the snapshots bucket only"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "ec2.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = { Name = "${local.name_prefix}-vm" }
}

resource "aws_iam_policy" "snapshots" {
  name        = "${local.name_prefix}-snapshots-bucket"
  description = "Allow S3 access to the demo snapshots bucket only"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [aws_s3_bucket.snapshots.arn]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:GetObjectAttributes",
          "s3:AbortMultipartUpload",
          "s3:ListMultipartUploadParts"
        ]
        Resource = ["${aws_s3_bucket.snapshots.arn}/*"]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "snapshots" {
  role       = aws_iam_role.demo.name
  policy_arn = aws_iam_policy.snapshots.arn
}

resource "aws_iam_instance_profile" "demo" {
  name = "${local.name_prefix}-vm"
  role = aws_iam_role.demo.name
}