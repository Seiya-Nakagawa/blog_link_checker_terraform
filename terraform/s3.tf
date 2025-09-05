resource "aws_s3_bucket" "s3_link_checker_results" {
  bucket = "${var.system_name}-${var.env}-s3-linkchecker-results"

  tags = {
    Name        = "${var.system_name}-${var.env}-s3-linkchecker-results",
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

# S3 Bucket Notification to trigger Lambda
resource "aws_s3_bucket_notification" "s3_lambda_trigger" {
  bucket = aws_s3_bucket.s3_link_checker_results.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.link_checker_lambda.arn
    events              = ["s3:ObjectCreated:Put"]
    filter_prefix       = "link-check-data/"
    filter_suffix       = ".json"
  }

  depends_on = [
    aws_lambda_permission.allow_s3_to_call_lambda
  ]
}
