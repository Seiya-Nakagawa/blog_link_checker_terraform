resource "aws_s3_bucket" "s3_link_checker" {
  bucket = "${var.system_name}-${var.env}-s3"

  tags = {
    Name       = "${var.system_name}-${var.env}-s3",
    SystemName = var.system_name,
    Env        = var.env,
  }
}

## 暗号化
resource "aws_s3_bucket_server_side_encryption_configuration" "s3_encryption_link_checker" {
  bucket = aws_s3_bucket.s3_link_checker.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

## バージョニング設定
resource "aws_s3_bucket_versioning" "versioning_link_checker_results" {
  bucket = aws_s3_bucket.s3_link_checker.id
  versioning_configuration {
    status = "Disabled"
  }
}

# S3 Bucket Notification to trigger Lambda
resource "aws_s3_bucket_notification" "s3_lambda_trigger" {
  bucket = aws_s3_bucket.s3_link_checker.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.link_checker_lambda.arn
    events              = ["s3:ObjectCreated:Put"]
    filter_prefix       = ""
    filter_suffix       = "urls_list.json"
  }

  depends_on = [
    aws_lambda_permission.allow_s3_to_call_lambda
  ]
}

resource "aws_s3_object" "folders" {
  # for_eachに、上で定義したフォルダ名のセットを渡します
  for_each = local.s3_folder_names

  # フォルダを作成したいバケットのIDを指定
  bucket = aws_s3_bucket.s3_link_checker.id

  # each.keyには、"gas_url/"、"processed_files/"などのフォルダ名が順番に入ります
  key = each.key

  # フォルダであることを示すContent-Type
  content_type = "application/x-directory"

  # 中身は空
  content = ""

  # 空のコンテンツのMD5ハッシュ値を指定
  etag = md5("")
}
