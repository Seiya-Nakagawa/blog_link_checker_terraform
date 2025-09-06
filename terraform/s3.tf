resource "aws_s3_bucket" "s3_link_checker" {
  bucket = "${var.system_name}-${var.env}-s3"

  tags = {
    Name        = "${var.system_name}-${var.env}-s3",
    SystemName  = var.system_name,
    Env         = var.env,
  }
}

resource "aws_s3_bucket_versioning" "versioning_link_checker_results" {
  bucket = aws_s3_bucket.s3_link_checker.id
  versioning_configuration {
    status = "Enabled"
  }
}

# S3 Bucket Notification to trigger Lambda
resource "aws_s3_bucket_notification" "s3_lambda_trigger" {
  bucket = aws_s3_bucket.s3_link_checker.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.link_checker_lambda.arn
    events              = ["s3:ObjectCreated:Put"]
    filter_prefix       = "gas_urls/"
    filter_suffix       = "urls_list.json"
  }

  depends_on = [
    aws_lambda_permission.allow_s3_to_call_lambda
  ]
}

# "gas_url/" フォルダを作成するためのS3オブジェクト
resource "aws_s3_object" "gas_url_folder" {
  # フォルダを作成したいバケットのIDを指定
  bucket = aws_s3_bucket.s3_link_checker.id

  # フォルダ名/ をキーとして指定
  key    = "gas_url/"

  # 中身は空のオブジェクトを作成
  content = ""
}