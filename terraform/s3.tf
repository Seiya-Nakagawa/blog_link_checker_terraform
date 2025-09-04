resource "aws_s3_bucket" "s3_link_checker_results" {
  bucket = "${var.system_name}-${var.env}-s3-link-checker-results"

  tags = {
    Name        = "${var.system_name}-${var.env}-s3-link-checker-results",
    SystemName  = var.system_name,
    Env         = var.env,
  }
}

resource "aws_s3_bucket_versioning" "versioning_link_checker_results" {
  bucket = aws_s3_bucket.s3_link_checker_results.id
  versioning_configuration {
    status = "Enabled"
  }
}