# Private snapshots bucket (PRD DEMO-FR-60, DG4, DEMO-NFR-05).
#
# Requirements met here:
#   * private             -> BucketOwnerEnforced ownership (ACLs disabled) +
#                            bucket-level Block Public Access
#   * SSE encryption      -> AES256 default encryption applied to every upload
#   * no public ACL       -> no aws_s3_bucket_acl resource at all; ownership
#                            control set to BucketOwnerEnforced
# Access is granted only through:
#   * the demo VM's IAM role (iam.tf) and
#   * short-lived presigned URLs minted by the backend.

resource "aws_s3_bucket" "snapshots" {
  bucket        = var.bucket_name
  force_destroy = false

  tags = { Name = "${local.name_prefix}-snapshots" }
}

resource "aws_s3_bucket_policy" "snapshots_tls" {
  bucket = aws_s3_bucket.snapshots.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Deny", Principal = "*", Action = "s3:*",
      Resource  = [aws_s3_bucket.snapshots.arn, "${aws_s3_bucket.snapshots.arn}/*"],
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_s3_bucket_ownership_controls" "snapshots" {
  bucket = aws_s3_bucket.snapshots.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "snapshots" {
  bucket = aws_s3_bucket.snapshots.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "snapshots" {
  bucket = aws_s3_bucket.snapshots.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "snapshots" {
  count = var.enable_bucket_versioning ? 1 : 0

  bucket = aws_s3_bucket.snapshots.id

  versioning_configuration {
    status = "Enabled"
  }
}
